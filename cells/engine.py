"""
Generic constraint propagation engine.

CONTRACT: this file contains NO domain knowledge. It never mentions a
specific field, unit, algorithm, or vocabulary. All domain content
arrives as declarative data from a pack.

Packs supply laws as DATA, never as code. The engine interprets a fixed
set of law forms. There is no eval(), no exec(), no import of pack code.
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
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

    @staticmethod
    def _dec(v):
        """Exact decimal. Never float: 0.1 + 0.2 != 0.3 would break equality."""
        try:
            return Decimal(str(v))
        except InvalidOperation:
            return None

    def _check_spec(self, cell: Cell, value):
        s = cell.spec
        if s.get("type") == "enum" and value not in s["values"]:
            raise Contradiction(cell.name, s["values"], value, "enum-spec")
        if s.get("type") == "decimal":
            d = self._dec(value)
            if d is None:
                raise Contradiction(cell.name, "a decimal", value, "type-spec")
            scale = s.get("scale", 2)
            if -d.as_tuple().exponent > scale:
                # finer than the domain can express: the same impossibility
                # that a non-integer k represents for an int cell
                raise Contradiction(cell.name, f"scale <= {scale}",
                                    str(d), "scale-spec")
            lo, hi = s.get("range", [None, None])
            if lo is not None and not (self._dec(lo) <= d <= self._dec(hi)):
                raise Contradiction(cell.name, f"[{lo},{hi}]", value, "range-spec")
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
        if cell.spec.get("type") == "decimal":
            value = self._dec(value)
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
                    # compare in the cell's own representation: a stored
                    # Decimal('0.55') will not equal the raw JSON float 0.55
                    def _same(rv):
                        if rv is None:
                            return False
                        if c.spec.get("type") == "decimal":
                            return self._dec(rv) == c.value
                        return rv == c.value
                    hits = [k for k, r in law["rows"].items() if _same(r.get(col))]
                    if len(hits) == 1:
                        changed |= self.bind(key, hits[0], law["id"], justification=[col])
        return changed

    def _fit(self, cell, value, law_id):
        """Coerce a derived value to the cell's type, or declare it impossible.

        This generalises the integer divisibility check: a non-integer for an
        int cell and a value finer than the declared scale for a decimal cell
        are the same kind of error - the law's own arithmetic says this value
        cannot hold.
        """
        spec = cell.spec
        if spec.get("type") == "int":
            if isinstance(value, Decimal):
                if value != value.to_integral_value():
                    raise Contradiction(cell.name, "an integer",
                                        str(value), law_id)
                return int(value)
            return value
        if spec.get("type") == "decimal":
            d = self._dec(value)
            scale = spec.get("scale", 2)
            q = d.quantize(Decimal(1).scaleb(-scale))
            if q != d:
                raise Contradiction(cell.name, f"scale <= {scale}",
                                    str(d), law_id)
            return q
        return value

    def _apply_affine(self, law):
        """target = a * source + b   (bidirectional)"""
        t, s = self.cells[law["target"]], self.cells[law["source"]]
        a, b = law["a"], law["b"]
        if "decimal" in (t.spec.get("type"), s.spec.get("type")) \
                or isinstance(a, float) or isinstance(b, float):
            a, b = self._dec(a), self._dec(b)

        if s.bound and not t.bound:
            v = self._fit(t, a * s.value + b, law["id"])
            return self.bind(t.name, v, law["id"], justification=[s.name])
        if t.bound and not s.bound and a != 0:
            num = t.value - b
            if isinstance(a, Decimal) or isinstance(num, Decimal):
                v = self._fit(s, self._dec(num) / self._dec(a), law["id"])
                return self.bind(s.name, v, law["id"], justification=[t.name])
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
