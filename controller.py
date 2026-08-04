#!/usr/bin/env python3
"""controller.py - the solve loop. Top-level entity of the runtime.

The model is a callable this invokes, not a thing that drives the system.
Contains no domain knowledge.

    proposer(cell_name, cell_spec, query) -> value | None

None means "not in the retrieved context" - a first-class answer that must
never be turned into a guess.
"""
from dataclasses import dataclass, field
from typing import Callable, Optional

from cells.engine import Network, Contradiction

MAX_RETRY = 2
DEFAULT_CONFIRM = 2


def _in_query(value, query):
    """Is this value literally present in the question? The runtime's only
    domain-agnostic defence against a model attributing a value it read from
    a chunk about something else."""
    return str(value).lower() in query.lower()


def _anchors(net):
    return {n: c.value for n, c in net.cells.items()
            if c.spec.get("anchor") and c.bound}


@dataclass
class Result:
    status: str
    net: Network
    conflict: Optional[tuple] = None
    rejected: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)
    confirmed: list = field(default_factory=list)

    @property
    def trustworthy(self):
        return self.status == "answered"

    def value(self, cell):
        return self.net.cells[cell].value if self.trustworthy else None

    def summary(self):
        s = self.net.stats()
        return {"status": self.status, "bound": s["bound"], "cells": s["cells"],
                "model_calls": s["model_calls"],
                "propagation_ratio": s["propagation_ratio"],
                "rejected": len(self.rejected),
                "unresolved": len(self.unresolved), "conflict": self.conflict}


def solve(schema, laws, query, proposer, confirm=DEFAULT_CONFIRM,
          max_retry=MAX_RETRY, force=None, verbose=False):
    net = Network(schema, laws)
    net.propagate()

    pending = dict(force or {})
    rejected, exhausted = [], set()

    while True:
        open_cells = [c for c in net.askable() if c not in exhausted]
        if not open_cells:
            break
        cell = open_cells[0]
        spec = net.cells[cell].spec
        bound = False
        anchors = _anchors(net)
        # With no anchor bound, a source-scoped value cannot be attributed to
        # any subject. Only the question itself is a legitimate source.
        question_only = (spec.get("scope") == "query"
                         or (spec.get("requires_anchor") and not anchors))

        for _ in range(max_retry + 1):
            if cell in pending:
                value = pending.pop(cell)
            else:
                try:
                    value = proposer(cell, spec, query, anchors=anchors,
                                     question_only=question_only)
                except TypeError:
                    value = proposer(cell, spec, query)
            if value is None:
                break
            if question_only and not _in_query(value, query):
                rejected.append((cell, value, "not stated in the question"))
                if verbose:
                    print(f"    rejected {cell}={value!r}: not in question")
                continue
            try:
                net.try_propose(cell, value, chunk_id="?", confidence=1.0)
                bound = True
                break
            except Contradiction as e:
                rejected.append((cell, value, str(e)))
                if verbose:
                    print(f"    rejected {cell}={value!r}")
        if not bound:
            exhausted.add(cell)

    for cell, value in pending.items():
        try:
            net.try_propose(cell, value, chunk_id="?", confidence=1.0)
        except Contradiction as e:
            rejected.append((cell, value, str(e)))

    # One root proposal leaves exactly one path to every derived cell, so a
    # wrong root propagates silently. Ask independently and compare.
    conflict, confirmed = None, []
    if confirm:
        cands = [n for n, c in net.cells.items()
                 if c.bound and c.source not in ("proposal", None)
                 and c.spec.get("confirmable", c.spec.get("askable", True))]
        cands.sort(key=lambda n: net.cells[n].spec.get("ask_cost", 100))
        for cell in cands[:confirm]:
            try:
                v = proposer(cell, net.cells[cell].spec, query,
                             anchors=_anchors(net), question_only=False)
            except TypeError:
                v = proposer(cell, net.cells[cell].spec, query)
            net.model_calls += 1
            if v is None:
                continue
            if v == net.cells[cell].value:
                confirmed.append(cell)
            else:
                conflict = (cell, net.cells[cell].value, v)
                if verbose:
                    print(f"    CONFLICT {cell}: derived "
                          f"{net.cells[cell].value!r} vs proposed {v!r}")
                break

    unresolved = net.unresolved()
    status = "conflict" if conflict else ("partial" if unresolved else "answered")
    return Result(status=status, net=net, conflict=conflict, rejected=rejected,
                  unresolved=unresolved, confirmed=confirmed)


def render(result, cells=None):
    """Prose rendered FROM the network. The model never writes the paragraph."""
    if result.status == "conflict":
        c, derived, proposed = result.conflict
        return (f"I can't answer this reliably. The pack's laws derive "
                f"{c} = {derived}, but reading the source independently gives "
                f"{proposed}. Something upstream is wrong, so I'm not "
                f"reporting any of it as fact.")
    lines = []
    for name, cell in result.net.cells.items():
        if cells and name not in cells:
            continue
        if cell.bound:
            src = "stated" if cell.source == "proposal" else f"derived via {cell.source}"
            lines.append(f"  {name} = {cell.value}   ({src})")
    out = "\n".join(lines) if lines else "  (nothing resolved)"
    if result.unresolved:
        out += "\n\nNot determinable from this pack: " + ", ".join(sorted(result.unresolved))
    return out
