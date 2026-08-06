#!/usr/bin/env python3
"""
verify_all_v1.py

Runs the three outstanding checks in one pass:

  1. probe_spans_v1 logic against the LIVE controller.py (imports it, does
     not copy the code) -- confirms the decimal/version fix is actually in
     the file being used, not just in a standalone copy.
  2. Provenance census over every dump present.
  3. Cross-pack summary of which cells are proposal-sourced.

Read-only. Nothing is written or modified.

    python verify_all_v1.py
"""

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------- 1. spans

VECTOR = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H base score 9.8"

CASES = [
    ("3.1", VECTOR, False, "CVSS spec version, not a value"),
    ("3.1", "exploitability 13.15 overall", False, "3.1 sits inside 13.15"),
    ("3.1", "Under CVSS 3.1, what is the sub-score?", False, "version, spaced form"),
    ("9.8", VECTOR, True, "real base score"),
    ("3.1", "the score is 3.1 exactly", True, "genuine standalone decimal"),
    ("31", "code 13154 here", False, "int inside longer int"),
    ("31", "count is 31 total", True, "standalone int"),
]


def check_spans():
    print("=" * 62)
    print("1. _spans against the LIVE controller.py")
    print("=" * 62)

    sys.path.insert(0, ".")
    try:
        import controller
    except Exception as e:
        print(f"  could not import controller.py: {e}")
        return

    fn = getattr(controller, "_spans", None)
    if fn is None:
        # _spans is nested inside _ambiguous_enum in some revisions
        print("  _spans not at module level -- checking for the guards instead")
        src = Path("controller.py").read_text()
        for marker, label in (
            ("_NUMERIC_FORM", "numeric-form patch"),
            ("_is_version_tag", "version-tag rejection"),
            ("return True", "fail-open adjacency (expected present)"),
        ):
            print(f"    {label:42s} {'PRESENT' if marker in src else 'ABSENT'}")
        return

    fails = 0
    for form, query, should, why in CASES:
        got = bool(fn(form, query))
        ok = got == should
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {form!r:6s} -> {got!s:5s} want {should!s:5s}  {why}")
    print(f"\n  {fails} failing case(s)")


# ------------------------------------------------------------ 2. provenance


def census():
    print()
    print("=" * 62)
    print("2. provenance census")
    print("=" * 62)

    dumps = sorted(Path(".").glob("prov_*.json"))
    if not dumps:
        print("  no prov_*.json found")
        return

    for p in dumps:
        try:
            d = json.load(open(p))
        except Exception as e:
            print(f"  {p.name:22s} unreadable: {e}")
            continue
        blob = json.dumps(d).lower()
        n_cases = len(d.get("cases", [])) if isinstance(d, dict) else "?"
        print(
            f"  {p.name:22s} cases={n_cases!s:4s}"
            f" proposal={blob.count('proposal'):4d}"
            f" derived={blob.count('derived'):4d}"
            f" held={blob.count('held'):4d}"
        )


# --------------------------------------------------------- 3. sourced cells


def sourced():
    print()
    print("=" * 62)
    print("3. proposal-sourced cells per dump")
    print("=" * 62)

    for p in sorted(Path(".").glob("prov_*.json")):
        try:
            d = json.load(open(p))
        except Exception:
            continue
        names = set()

        def walk(node):
            if isinstance(node, dict):
                blob = json.dumps(node).lower()
                if "proposal" in blob or "oracle" in blob:
                    for k in ("cell", "name", "id", "target"):
                        v = node.get(k)
                        if isinstance(v, str) and len(v) < 40:
                            names.add(v)
                            break
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(d)
        if names:
            print(f"  {p.name}")
            for n in sorted(names)[:12]:
                print(f"      {n}")


if __name__ == "__main__":
    check_spans()
    census()
    sourced()
    print("\ndone -- read-only, nothing modified.")
