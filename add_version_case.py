#!/usr/bin/env python3
"""
add_version_case.py

Adds one adversarial case that exercises the guard we just patched:
a query that names NO cell but DOES carry a stray number.

Before the fail-closed patch: "3.1" is the lone numeric candidate, the cue
is absent so _near_span returns True, and it binds -- leaking a value into
a cell that should stay open.

After: no adjacency evidence, so it abstains.

Idempotent. Backs up cases.json before writing.
"""

import json
import shutil
import sys
from pathlib import Path

P = Path("../pack-cvss/eval/cases.json")

CASE = {
    "id": "version-number-not-a-value",
    "query": "Under CVSS 3.1, what is the exploitability sub-score here?",
    "truth": {},
    "expect_open": ["av_weight", "exploitability_term", "remote"],
}


def main():
    if not P.exists():
        print(f"ABORT: {P} not found -- run from ~/domain-runtime")
        sys.exit(1)

    d = json.load(open(P))
    if any(c.get("id") == CASE["id"] for c in d["cases"]):
        print("already present -- nothing to do")
        return

    shutil.copy2(P, str(P) + ".bak_versioncase")
    d["cases"].append(CASE)
    json.dump(d, open(P, "w"), indent=2)
    print(f"added -> {len(d['cases'])} cases total")
    print("\nWATCH FOR: abstention should stay 1.000 with leaked 0.")
    print("A leaked 1 means the bug reproduced and the patch is load-bearing.")


if __name__ == "__main__":
    main()
