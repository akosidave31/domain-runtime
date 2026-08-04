#!/usr/bin/env python3
"""eval_runner.py - scores a pack against its own held-out eval set.

    python eval_runner.py ../pack-pqc
    python eval_runner.py ../pack-pqc --noise 0.3
    python eval_runner.py ../pack-pqc --noise 0.3 --confirm 3
"""
import json, os, random, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cells.engine import Network, Contradiction

MAX_RETRY = 2


def oracle(truth):
    def p(cell, spec, query):
        return truth.get(cell)
    return p


def noisy(truth, rate, rng):
    def p(cell, spec, query):
        v = truth.get(cell)
        if v is None:
            return None
        if rng.random() >= rate:
            return v
        if spec.get("type") == "enum":
            alts = [x for x in spec["values"] if x != v]
            return rng.choice(alts) if alts else v
        lo, hi = spec.get("range", [0, 100])
        for _ in range(20):
            c = rng.randint(lo, hi)
            if c != v:
                return c
        return v
    return p


def solve(schema, laws, case, proposer, verbose=False, confirm=0):
    net = Network(schema, laws)
    net.propagate()
    injected = dict(case.get("inject") or {})
    rejected, exhausted = [], set()

    while True:
        open_cells = [c for c in net.askable() if c not in exhausted]
        if not open_cells:
            break
        cell = open_cells[0]
        spec = net.cells[cell].spec
        bound_ok = False
        for _ in range(MAX_RETRY + 1):
            if cell in injected:
                value = injected.pop(cell)
            else:
                value = proposer(cell, spec, case["query"])
            if value is None:
                break
            try:
                net.propose(cell, value, chunk_id="eval", confidence=1.0)
                net.propagate()
                bound_ok = True
                break
            except Contradiction as e:
                rejected.append((cell, value, str(e)))
                if verbose:
                    print(f"      rejected {cell}={value!r}")
        if not bound_ok:
            exhausted.add(cell)

    for cell, value in injected.items():
        try:
            net.propose(cell, value, chunk_id="eval", confidence=1.0)
            net.propagate()
        except Contradiction as e:
            rejected.append((cell, value, str(e)))

    # confirmation: a single root proposal leaves only one path to each
    # derived cell, so a wrong root propagates silently. Ask independently.
    conflict = None
    if confirm:
        derived = [n for n, c in net.cells.items()
                   if c.bound and c.source not in ("proposal", None)
                   and c.spec.get("askable", True)]
        derived.sort(key=lambda n: net.cells[n].spec.get("ask_cost", 100))
        for cell in derived[:confirm]:
            v = proposer(cell, net.cells[cell].spec, case["query"])
            net.model_calls += 1
            if v is None:
                continue
            if v != net.cells[cell].value:
                conflict = (cell, net.cells[cell].value, v)
                if verbose:
                    print(f"      CONFLICT {cell}: derived "
                          f"{net.cells[cell].value!r} vs proposed {v!r}")
                break
    return net, rejected, conflict


def score(pack, noise, seed, verbose, confirm=0):
    schema = json.load(open(os.path.join(pack, "cells/schema.json")))
    laws = json.load(open(os.path.join(pack, "cells/laws.json")))["laws"]
    cases = json.load(open(os.path.join(pack, "eval/cases.json")))["cases"]
    rng = random.Random(seed)
    tot = {"exp": 0, "ok": 0, "wrong": 0, "missing": 0, "open_exp": 0,
           "open_ok": 0, "leaked": 0, "calls": 0, "derived": 0, "bound": 0,
           "rejected": 0, "conflicts": 0, "silent": 0}
    failures = []

    for case in cases:
        truth = case.get("truth", {})
        p = oracle(truth) if noise == 0 else noisy(truth, noise, rng)
        net, rejected, conflict = solve(schema, laws, case, p, verbose, confirm)
        if conflict:
            tot["conflicts"] += 1
        if verbose:
            print(f"\n  {case['id']}: {case['query']}")

        for cell, want in case.get("expect", {}).items():
            tot["exp"] += 1
            got = net.cells[cell].value
            if got == want:
                tot["ok"] += 1
            elif got is None:
                tot["missing"] += 1
                failures.append((case["id"], cell, want, "unresolved"))
            else:
                tot["wrong"] += 1
                if not conflict:
                    tot["silent"] += 1
                failures.append((case["id"], cell, want, got))

        for cell in case.get("expect_open", []):
            tot["open_exp"] += 1
            if net.cells[cell].value is None:
                tot["open_ok"] += 1
            else:
                tot["leaked"] += 1
                failures.append((case["id"], cell, "ABSTAIN", net.cells[cell].value))

        s = net.stats()
        tot["calls"] += s["model_calls"]
        tot["derived"] += s["derived"]
        tot["bound"] += s["bound"]
        tot["rejected"] += len(rejected)
        if verbose:
            print(f"      calls={s['model_calls']} ratio={s['propagation_ratio']}"
                  f" rejected={len(rejected)}")

    n = len(cases)
    acc = tot["ok"] / tot["exp"] if tot["exp"] else 0
    abst = tot["open_ok"] / tot["open_exp"] if tot["open_exp"] else 1.0
    ratio = tot["derived"] / tot["bound"] if tot["bound"] else 0
    label = "oracle" if noise == 0 else f"noisy p={noise}"

    print(f"\n{'='*54}")
    print(f"pack: {os.path.basename(os.path.abspath(pack))}   "
          f"proposer: {label}   confirm: {confirm}   cases: {n}")
    print(f"{'='*54}")
    print(f"  extraction accuracy   {acc:.3f}   ({tot['ok']}/{tot['exp']}  "
          f"wrong {tot['wrong']}, unresolved {tot['missing']})")
    print(f"  abstention accuracy   {abst:.3f}   ({tot['open_ok']}/"
          f"{tot['open_exp']}  leaked {tot['leaked']})")
    print(f"  propagation ratio     {ratio:.3f}   ({tot['derived']} derived / "
          f"{tot['bound']} bound)")
    print(f"  model calls / query   {tot['calls']/n:.2f}")
    print(f"  proposals rejected    {tot['rejected']}")
    print(f"  conflicts detected    {tot['conflicts']} / {n} cases")
    print(f"  SILENT errors         {tot['silent']}   (wrong, nothing flagged it)")

    if failures:
        print("\n  failures:")
        for cid, cell, want, got in failures:
            print(f"    {cid:<24} {cell:<12} want {want!r}, got {got!r}")
    return acc, abst, ratio


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    noise = float(sys.argv[sys.argv.index("--noise") + 1]) if "--noise" in sys.argv else 0.0
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 7
    confirm = int(sys.argv[sys.argv.index("--confirm") + 1]) if "--confirm" in sys.argv else 0
    score(args[0], noise, seed, "--verbose" in sys.argv, confirm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
