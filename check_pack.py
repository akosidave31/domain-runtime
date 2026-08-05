#!/usr/bin/env python3
"""check_pack.py - is this pack internally coherent?

    python check_pack.py ../pack-quantum

validate_pack.py checks FORMAT: are the files present and well-formed.
This checks CONTENT: do the pack's own declarations agree with each other,
and can the model actually find what the pack claims.

Every check here corresponds to a bug that was found the hard way.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cells.engine import Network, Contradiction
from retrieve import load_chunks

E, W = [], []


def err(m):
    E.append(m)


def warn(m):
    W.append(m)


def check_law_consistency(schema, laws):
    """Bind each anchor value in turn. Every one must resolve without conflict."""
    anchors = [n for n, c in schema["cells"].items() if c.get("anchor")]
    if not anchors:
        err("no anchor cell declared")
        return
    for a in anchors:
        spec = schema["cells"][a]
        if spec.get("type") != "enum":
            continue
        for v in spec["values"]:
            net = Network(schema, laws)
            try:
                net.propagate()
                net.bind(a, v, "check")
                net.propagate()
            except Contradiction as e:
                err(f"anchor {a}={v!r} contradicts the pack's own laws: {e}")
                continue
            open_cells = net.unresolved()
            if open_cells:
                warn(f"anchor {a}={v!r} leaves {sorted(open_cells)} unresolved - "
                     f"the model will have to supply them on every query")


def check_corpus_coverage(pack, schema, laws):
    """Every value the laws declare must appear in the corpus.

    A pack can declare AES-192 has key_bits 192 while the knowledge never
    says so. Propagation would still derive it, but the model could never
    legitimately propose it, and confirmation would always fail.
    """
    try:
        chunks = load_chunks(pack)
    except SystemExit:
        err("no knowledge/*.md - the model has nothing to read")
        return
    text = " ".join(c["text"] for c in chunks).lower()

    for law in laws:
        if law.get("form") != "table":
            continue
        for rowkey, row in law.get("rows", {}).items():
            if rowkey.lower() not in text:
                err(f"table key {rowkey!r} never appears in knowledge/")
            for cell, val in row.items():
                if not re.search(r"(?<!\d)" + str(val) + r"(?!\d)", text):
                    err(f"{rowkey}.{cell} = {val} never appears in knowledge/ - "
                        f"the model cannot read it, only propagation can "
                        f"produce it")


def check_range_tightness(schema, laws):
    """Ranges are part of verification. A range far wider than the values the
    pack can actually produce is a hole a misattributed value fits through.
    """
    reachable = {}
    for law in laws:
        if law.get("form") != "table":
            continue
        for row in law.get("rows", {}).values():
            for cell, val in row.items():
                reachable.setdefault(cell, set()).add(val)

    for _ in range(4):
        for law in laws:
            if law.get("form") != "affine":
                continue
            t, s = law["target"], law["source"]
            a, b = law["a"], law["b"]
            for v in list(reachable.get(s, [])):
                reachable.setdefault(t, set()).add(a * v + b)
            for v in list(reachable.get(t, [])):
                if a and (v - b) % a == 0:
                    reachable.setdefault(s, set()).add((v - b) // a)

    for cell, vals in reachable.items():
        spec = schema["cells"].get(cell, {})
        rng = spec.get("range")
        if not rng or spec.get("type") != "int":
            continue
        lo, hi = min(vals), max(vals)
        if rng[1] - rng[0] > max(4 * (hi - lo + 1), 64):
            warn(f"cell {cell!r} range {rng} is far wider than the values the "
                 f"pack can produce ({sorted(vals)}). Tighten toward "
                 f"[{lo}, {hi}] - a loose range lets a misattributed value "
                 f"pass the spec check")


def check_eval_derivable(schema, laws, cases):
    """Every expected value must follow from that case's truth."""
    for c in cases:
        truth = c.get("truth", {})
        net = Network(schema, laws)
        try:
            net.propagate()
            for cell, v in truth.items():
                net.bind(cell, v, "check")
                net.propagate()
        except Contradiction as e:
            err(f"eval case {c['id']!r}: its own truth is contradictory: {e}")
            continue
        for cell, want in c.get("expect", {}).items():
            got = net.cells[cell].value
            if got is None:
                err(f"eval case {c['id']!r} expects {cell}={want} but truth "
                    f"{truth} does not determine it - unwinnable case")
            elif got != want:
                err(f"eval case {c['id']!r} expects {cell}={want} but the laws "
                    f"derive {got} - the case or the laws are wrong")
        for cell in c.get("expect_open", []):
            if net.cells[cell].value is not None:
                err(f"eval case {c['id']!r} expects {cell} to stay open but "
                    f"truth {truth} determines it")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    pack = os.path.abspath(sys.argv[1])
    schema = json.load(open(os.path.join(pack, "cells/schema.json")))
    laws = json.load(open(os.path.join(pack, "cells/laws.json")))["laws"]
    cp = os.path.join(pack, "eval/cases.json")
    cases = json.load(open(cp))["cases"] if os.path.exists(cp) else []

    check_law_consistency(schema, laws)
    check_corpus_coverage(pack, schema, laws)
    check_range_tightness(schema, laws)
    check_eval_derivable(schema, laws, cases)

    print(f"\npack: {os.path.basename(pack)}   "
          f"{len(schema['cells'])} cells, {len(laws)} laws, {len(cases)} cases")
    for x in W:
        print(f"  warn   {x}")
    for x in E:
        print(f"  ERROR  {x}")
    print("\n" + (f"INCOHERENT  {len(E)} error(s)" if E
                  else f"COHERENT  {len(W)} warning(s)"))
    return 1 if E else 0


if __name__ == "__main__":
    sys.exit(main())
