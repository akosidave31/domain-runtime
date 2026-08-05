import json, sys
a_p, b_p = sys.argv[1], sys.argv[2]
A = json.load(open(a_p)); B = json.load(open(b_p))
ids = sorted(set(A) | set(B))
same = 0; diffs = []
for cid in ids:
    a, b = A.get(cid), B.get(cid)
    if a is None or b is None:
        diffs.append((cid, "missing from one run")); continue
    av = {k: v["value"] for k, v in a["cells"].items()}
    bv = {k: v["value"] for k, v in b["cells"].items()}
    ao = {k: v["origin"] for k, v in a["cells"].items()}
    bo = {k: v["origin"] for k, v in b["cells"].items()}
    if av == bv and ao == bo:
        same += 1; continue
    if av == bv:
        f = [k for k in ao if ao[k] != bo.get(k)]
        diffs.append((cid, "same values, ORIGIN FLIPPED: %s" % f)); continue
    oa = sorted(set(av) - set(bv)); ob = sorted(set(bv) - set(av))
    mm = sorted(k for k in set(av) & set(bv) if av[k] != bv[k])
    p = []
    if oa: p.append("only A: %s" % oa)
    if ob: p.append("only B: %s" % ob)
    if mm: p.append("VALUE MISMATCH: %s" % mm)
    diffs.append((cid, "; ".join(p)))
print("=" * 54)
print("A=%s  B=%s" % (a_p, b_p))
print("=" * 54)
print("  cases            %d" % len(ids))
print("  identical        %d" % same)
print("  differing        %d" % len(diffs))
for cid, why in diffs:
    print("    %-22s %s" % (cid, why))
for lbl, D in ((a_p, A), (b_p, B)):
    calls = sum(c["calls"] for c in D.values())
    rej = sum(len(c["rejected"]) for c in D.values())
    rt = sum(1 for c in D.values() for x in c["cells"].values() if x["origin"] == "proposal")
    roots = sorted(set(k for c in D.values() for k, x in c["cells"].items() if x["origin"] == "proposal"))
    print("\n  %s: %d calls, %d rejected, %d proposal roots %s" % (lbl, calls, rej, rt, roots))
print()
print("VERDICT: identical networks -- eval set cannot distinguish proposers" if same == len(ids) else "VERDICT: runs diverge -- see cases above")
