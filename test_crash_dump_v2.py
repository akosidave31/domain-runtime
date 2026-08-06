#!/usr/bin/env python3
"""
test_crash_dump_v2.py

v1 failed to force a crash: the oracle ignores truth keys for cells it is
not asked about, so an inconsistent truth value changed nothing.

We are testing the crash HANDLER, not the contradiction engine, so any
mid-loop exception will do. This inserts a case with query=None at position
5, which raises inside the string/regex handling.

Position 5 matters: it means 5 cases complete first, so a correct handler
should capture those 5 in the partial dump. That proves it saves work in
progress, not just that it runs.

Your real pack is never touched -- everything happens in ~/pack-crashtest.

    python test_crash_dump_v2.py
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path("../pack-cvss")
TMP = Path(os.path.expanduser("~/pack-crashtest"))
DUMP = "prov_crashtest.json"
PARTIAL = DUMP + ".partial"
POS = 5


def cleanup():
    if TMP.exists():
        shutil.rmtree(TMP)


def main():
    if not SRC.exists():
        print("ABORT: ../pack-cvss not found -- run from ~/domain-runtime")
        sys.exit(1)
    if "_emergency_dump" not in Path("eval_runner.py").read_text():
        print("ABORT: eval_runner.py is not patched")
        sys.exit(1)

    for f in (DUMP, PARTIAL):
        if Path(f).exists():
            Path(f).unlink()

    cleanup()
    shutil.copytree(SRC, TMP)

    cp = TMP / "eval" / "cases.json"
    d = json.load(open(cp))
    before = [c["id"] for c in d["cases"][:POS]]

    d["cases"].insert(POS, {
        "id": "deliberate-crash-probe",
        "query": None,
        "truth": {},
    })
    json.dump(d, open(cp, "w"), indent=2)

    print(f"inserted 'deliberate-crash-probe' (query=None) at position {POS}")
    print(f"cases expected to complete first: {before}\n")

    print("=" * 60)
    r = subprocess.run(
        [sys.executable, "eval_runner.py", str(TMP), "--dump", DUMP],
        capture_output=True, text=True,
    )
    out = (r.stdout or "") + (r.stderr or "")
    print(out[-2000:])
    print("=" * 60)

    print(f"\nexit code: {r.returncode}")

    if r.returncode == 0:
        print("\nSTILL NO CRASH -- query=None was tolerated.")
        print("The runner is more defensive than expected. Handler untested.")
        cleanup()
        return

    ok_partial = Path(PARTIAL).exists()
    ok_named = "deliberate-crash-probe" in out

    print(f"  partial dump written    {'YES' if ok_partial else 'NO'}")
    print(f"  crash names the case    {'YES' if ok_named else 'NO'}")

    if ok_partial:
        p = json.load(open(PARTIAL))
        print(f"  cases captured          {len(p)} (expected {POS})")
        print(f"  ids                     {list(p)}")
        if len(p) == POS:
            print("  -> prior work preserved exactly")

    if ok_partial and ok_named:
        print("\nPASS -- at 19:28 this would have named the failing case and")
        print("saved every case before it. That is the whole point.")
    else:
        print("\nFAIL -- handler did not fire. Traceback above.")

    cleanup()
    print(f"\nremoved {TMP}; kept {PARTIAL} for inspection")


if __name__ == "__main__":
    main()
