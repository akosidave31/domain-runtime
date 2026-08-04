#!/usr/bin/env python3
"""eval_runner.py - scores a pack against its own held-out eval set.

    python eval_runner.py ../pack-pqc
    python eval_runner.py ../pack-pqc --noise 0.3 --confirm 3
    python eval_runner.py ../pack-pqc --llm --confirm 3 --verbose
"""
import glob, json, os, random, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from controller import solve as controller_solve


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


def load_context(pack):
    parts = [open(f).read()
             for f in sorted(glob.glob(os.path.join(pack, "knowledge", "*.md")))]
    if not parts:
        raise SystemExit(f"no knowledge/*.md in {pack}")
    return "\n\n".join(parts)


def score(pack, noise, seed, verbose, confirm=0, use_llm=False, endpoint=None):
    schema = json.load(open(os.path.join(pack, "cells/schema.json")))
    laws = json.load(open(os.path.join(pack, "cells/laws.json")))["laws"]
    cases = json.load(open(os.path.join(pack, "eval/cases.json")))["cases"]
    rng = random.Random(seed)

    llm_proposer = None
    if use_llm:
        from llm import make_proposer, ENDPOINT
        llm_proposer = make_proposer(load_context(pack), endpoint or ENDPOINT, verbose)

    tot = {"exp": 0, "ok": 0, "wrong": 0, "missing": 0, "open_exp": 0,
           "open_ok": 0, "leaked": 0, "calls": 0, "derived": 0, "bound": 0,
           "rejected": 0, "conflicts": 0, "silent": 0}
    failures = []

    for case in cases:
        truth = case.get("truth", {})
        if llm_proposer is not None:
            p = llm_proposer
        else:
            p = oracle(truth) if noise == 0 else noisy(truth, noise, rng)

        if verbose:
            print(f"\n  {case['id']}: {case['query']}")

        r = controller_solve(schema, laws, case["query"], p, confirm=confirm,
                             force=case.get("inject"), verbose=verbose)
        net, rejected, conflict = r.net, r.rejected, r.conflict
        if conflict:
            tot["conflicts"] += 1

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
            print(f"      status={r.status} calls={s['model_calls']} "
                  f"ratio={s['propagation_ratio']} rejected={len(rejected)}")

    n = len(cases)
    acc = tot["ok"] / tot["exp"] if tot["exp"] else 0
    abst = tot["open_ok"] / tot["open_exp"] if tot["open_exp"] else 1.0
    ratio = tot["derived"] / tot["bound"] if tot["bound"] else 0
    label = "llm" if use_llm else ("oracle" if noise == 0 else f"noisy p={noise}")

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
    ep = sys.argv[sys.argv.index("--endpoint") + 1] if "--endpoint" in sys.argv else None
    score(args[0], noise, seed, "--verbose" in sys.argv, confirm, "--llm" in sys.argv, ep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
