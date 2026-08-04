"""
Generic constraint propagation engine.

CONTRACT: this file contains NO domain knowledge. It never mentions a
specific field, unit, algorithm, or vocabulary. All domain content
arrives as declarative data from a pack.

Packs supply laws as DATA, never as code. The engine interprets a fixed
set of law forms. There is no eval(), no exec(), no import of pack code.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


class Contradiction(Exception):
    def __init__(self, cell, existing, proposed, law):
        self.cell, self.existing, self.proposed, self.law = cell, existing, proposed, law
        super().__init__(
            f"cell '{cell}': held {existing!r}, derived {proposed!r} via {law}"
        )


@dataclass
class Cell:
    name: str
    spec: dict
    value: Any = None
    source: Optional[str] = None        # 'given' | 'proposal' | law id
    confidence: Optional[float] = None
    chunk_id: Optional[str] = None      # provenance for proposals
    justification: list = field(default_factory=list)

    @property
    def bound(self) -> bool:
        return self.value is not None


class Network:
    """Cells + laws. Propagates until fixpoint. Reports what is still open."""

    def __init__(self, schema: dict, laws: list):
        self.cells = {n: Cell(n, s) for n, s in schema["cells"].items()}
        self.laws = laws
        self.model_calls = 0
        self.derived = 0

    # ---------- binding ----------

    def _check_spec(self, cell: Cell, value):
        s = cell.spec
        if s.get("type") == "enum" and value not in s["values"]:
            raise Contradiction(cell.name, s["values"], value, "enum-spec")
        if s.get("type") == "int":
            if not isinstance(value, int):
                raise Contradiction(cell.name, "int", value, "type-spec")
            lo, hi = s.get("range", [None, None])
            if lo is not None and not (lo <= value <= hi):
                raise Contradiction(cell.name, f"[{lo},{hi}]", value, "range-spec")

    def bind(self, name, value, source, *, confidence=None, chunk_id=None,
             justification=None):
        cell = self.cells[name]
        self._check_spec(cell, value)
        if cell.bound:
            if cell.value != value:
                raise Contradiction(name, cell.value, value, source)
            return False
        cell.value = value
        cell.source = source
        cell.confidence = confidence
        cell.chunk_id = chunk_id
        cell.justification = justification or []
        if source not in ("given", "proposal"):
            self.derived += 1
        return True

    def propose(self, name, value, *, chunk_id, confidence):
        """A model proposal. Counted separately from derivation."""
        self.model_calls += 1
        return self.bind(name, value, "proposal",
                         confidence=confidence, chunk_id=chunk_id)

    def _snapshot(self):
        return ({n: (c.value, c.source, c.confidence, c.chunk_id,
                     tuple(c.justification)) for n, c in self.cells.items()},
                self.derived)

    def _restore(self, snap):
        state, derived = snap
        for n, (v, src, cf, ch, j) in state.items():
            c = self.cells[n]
            c.value, c.source, c.confidence = v, src, cf
            c.chunk_id, c.justification = ch, list(j)
        self.derived = derived

    def try_propose(self, name, value, *, chunk_id=None, confidence=None):
        """Atomic: propose + propagate, or leave the network untouched.

        Without this, a proposal that binds cleanly but contradicts two laws
        later leaves its bad value behind - the contradiction is logged while
        the corruption stays.
        """
        snap = self._snapshot()
        self.model_calls += 1
        try:
            self.bind(name, value, "proposal",
                      confidence=confidence, chunk_id=chunk_id)
            self.propagate()
            return True
        except Contradiction:
            self._restore(snap)
            raise

    # ---------- law forms ----------

    def _apply_table(self, law):
        changed = False
        key = law["key"]
        kc = self.cells[key]
        if kc.bound:
            row = law["rows"].get(str(kc.value))
            if row:
                for target, v in row.items():
                    changed |= self.bind(target, v, law["id"], justification=[key])
        else:
            # reverse lookup: any bound column that uniquely identifies a row
            for col in law.get("identifying", []):
                c = self.cells.get(col)
                if c and c.bound:
                    hits = [k for k, r in law["rows"].items() if r.get(col) == c.value]
                    if len(hits) == 1:
                        changed |= self.bind(key, hits[0], law["id"], justification=[col])
        return changed

    def _apply_affine(self, law):
        """target = a * source + b   (bidirectional)"""
        t, s, a, b = self.cells[law["target"]], self.cells[law["source"]], law["a"], law["b"]
        if s.bound and not t.bound:
            return self.bind(t.name, a * s.value + b, law["id"], justification=[s.name])
        if t.bound and not s.bound and a != 0:
            num = t.value - b
            if num % a:
                # target implies a non-integer source, but the source is an
                # int cell. The target value is impossible under this law -
                # not merely underdetermined. Staying silent here let a model
                # bind 3168 to ek_bytes (implying k = 8.166) unchallenged.
                raise Contradiction(s.name, "an integer",
                                    f"{num}/{a}", law["id"])
            return self.bind(s.name, num // a, law["id"], justification=[t.name])
        if s.bound and t.bound and t.value != a * s.value + b:
            raise Contradiction(t.name, t.value, a * s.value + b, law["id"])
        return False

    def _apply_bilinear(self, law):
        """target = scale * ( sum(prod of pair) + sum(plus) )   single-unknown solve"""
        names = set()
        for pair in law.get("terms", []):
            names.update(pair)
        names.update(law.get("plus", []))
        names.add(law["target"])

        unknown = [n for n in names if not self.cells[n].bound]
        if len(unknown) > 1:
            return False

        def val(n):
            return self.cells[n].value

        if not unknown:  # all bound -> verify
            total = sum(val(p[0]) * val(p[1]) for p in law.get("terms", []))
            total += sum(val(n) for n in law.get("plus", []))
            expect = law["scale"] * total
            if val(law["target"]) != expect:
                raise Contradiction(law["target"], val(law["target"]), expect, law["id"])
            return False

        u = unknown[0]
        just = sorted(names - {u})
        if u == law["target"]:
            total = sum(val(p[0]) * val(p[1]) for p in law.get("terms", []))
            total += sum(val(n) for n in law.get("plus", []))
            return self.bind(u, law["scale"] * total, law["id"], justification=just)

        # solve for an input
        rhs = val(law["target"]) / law["scale"]
        coeff, const = 0, 0
        for x, y in law.get("terms", []):
            if x == u:
                coeff += val(y)
            elif y == u:
                coeff += val(x)
            else:
                const += val(x) * val(y)
        for n in law.get("plus", []):
            if n == u:
                coeff += 1
            else:
                const += val(n)
        if coeff == 0:
            return False
        num = rhs - const
        if num % coeff:
            raise Contradiction(u, "an integer", f"{num}/{coeff}", law["id"])
        return self.bind(u, int(num // coeff), law["id"], justification=just)

    def _apply_constant(self, law):
        return self.bind(law["cell"], law["value"], law["id"])

    _FORMS = {
        "table": _apply_table,
        "affine": _apply_affine,
        "bilinear": _apply_bilinear,
        "constant": _apply_constant,
    }

    # ---------- fixpoint ----------

    def propagate(self, max_rounds=64) -> int:
        rounds = 0
        while rounds < max_rounds:
            rounds += 1
            changed = False
            for law in self.laws:
                fn = self._FORMS.get(law["form"])
                if fn:
                    changed |= bool(fn(self, law))
            if not changed:
                break
        return rounds

    # ---------- reporting ----------

    def unresolved(self):
        return [n for n, c in self.cells.items() if not c.bound]

    def askable(self):
        """Unresolved cells a model could reasonably propose, cheapest first."""
        open_ = [self.cells[n] for n in self.unresolved()]
        open_.sort(key=lambda c: c.spec.get("ask_cost", 100))
        return [c.name for c in open_ if c.spec.get("askable", True)]

    def stats(self):
        bound = sum(1 for c in self.cells.values() if c.bound)
        return {
            "cells": len(self.cells),
            "bound": bound,
            "model_calls": self.model_calls,
            "derived": self.derived,
            "propagation_ratio": round(self.derived / bound, 3) if bound else 0.0,
        }

    def trace(self):
        out = []
        for n, c in self.cells.items():
            if not c.bound:
                out.append(f"  {n:<14} OPEN")
            else:
                why = c.source if not c.justification else \
                    f"{c.source}  <- {', '.join(c.justification)}"
                out.append(f"  {n:<14} {str(c.value):<14} {why}")
        return "\n".join(out)
