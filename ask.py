#!/usr/bin/env python3
"""ask.py - the entry point. Query in, verified answer or abstention out.

    python ask.py "What is the ciphertext size of ML-KEM-768?"
    python ask.py --dry "..."        plumbing only, no model
    python ask.py --trace "..."      show how each cell was bound

Pipeline: route -> retrieve -> solve -> confirm -> render.
The model is called only for cells the runtime could not decide itself.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from router import load_profiles, route
from retrieve import load_chunks, build_index, context_for
from controller import solve, render

CONFIRM = 2
TOPK = 2


def null_proposer(cell, spec, query, anchors=None, question_only=False):
    """Answers nothing. Exercises the whole pipeline with no model."""
    return None


def ask(query, sources="sources.json", dry=False, trace=False, topk=TOPK,
        confirm=CONFIRM):
    here = os.path.dirname(os.path.abspath(__file__))
    packs = json.load(open(os.path.join(here, sources)))["packs"]
    packs = [p if os.path.isabs(p) else os.path.join(here, p) for p in packs]

    profiles = load_profiles(packs)
    pack, reason, _ = route(query, profiles)
    if pack is None:
        return (f"No pack covers this question ({reason}).\n"
                f"Answering anyway would mean answering from a corpus that is "
                f"about something else.")

    d = pack["dir"]
    schema = json.load(open(os.path.join(d, "cells/schema.json")))
    laws = json.load(open(os.path.join(d, "cells/laws.json")))["laws"]

    chunks = load_chunks(d)
    idf = build_index(chunks)
    ctx = context_for(chunks, idf, query, k=topk)

    if dry:
        proposer = null_proposer
    else:
        from llm import make_proposer
        proposer = make_proposer(ctx, verbose=trace)

    result = solve(schema, laws, query, proposer, confirm=confirm, verbose=trace)

    head = f"[{pack['id']}]  {reason}"
    body = render(result)
    tail = f"\n\n{json.dumps(result.summary(), indent=2)}" if trace else ""
    return f"{head}\n\n{body}{tail}"


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(2)
    print(ask(" ".join(args), dry="--dry" in sys.argv, trace="--trace" in sys.argv))
