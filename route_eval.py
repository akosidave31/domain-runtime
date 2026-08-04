#!/usr/bin/env python3
"""route_eval.py - scores the router. Routing needs a gate like everything else.

    python route_eval.py route_cases.json

Three error types, not equally bad:
  MISROUTE - wrong pack. It will answer from the wrong corpus.
  MISSED   - abstained on a query a pack covers. User gets nothing.
  LEAKED   - routed a query no pack covers. The worst of the three.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from router import load_profiles, route


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    spec = json.load(open(sys.argv[1]))
    profiles = load_profiles(spec["packs"])
    ok = misroute = missed = leaked = 0
    fails = []

    for c in spec["cases"]:
        want = c.get("pack")
        pack, reason, _ = route(c["query"], profiles)
        got = pack["id"] if pack else None
        if got == want:
            ok += 1
        elif want is None:
            leaked += 1
            fails.append(("LEAKED  ", c["query"], got, want))
        elif got is None:
            missed += 1
            fails.append(("MISSED  ", c["query"], got, want))
        else:
            misroute += 1
            fails.append(("MISROUTE", c["query"], got, want))

    n = len(spec["cases"])
    print(f"\n{'='*54}\nrouting: {n} cases, {len(profiles)} packs\n{'='*54}")
    print(f"  accuracy    {ok/n:.3f}   ({ok}/{n})")
    print(f"  MISROUTE    {misroute}   (wrong pack - answers from wrong corpus)")
    print(f"  MISSED      {missed}   (abstained on a covered query)")
    print(f"  LEAKED      {leaked}   (routed an uncovered query)")
    for kind, q, got, want in fails:
        print(f"    {kind}  {str(want):<9} -> {str(got):<9} {q[:40]}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
