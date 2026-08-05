import json, shutil
P = "../pack-cvss/eval/cases.json"
NEW = [
 # bare "Adjacent" with no "Network" -- alias must not be required to match
 {"id": "adjacent-bare",
  "query": "What is the CVSS 3.1 weight for the Adjacent attack vector?",
  "truth": {"attack_vector": "Adjacent", "av_weight": 0.62},
  "expect": {"av_weight": 0.62, "exploitability_term": 5.0964, "remote": "no"}},
 # two genuinely different vectors named -- must still abstain
 {"id": "two-vectors-ambiguous",
  "query": "Is the Local attack vector weight higher than Physical?",
  "truth": {},
  "expect_open": ["attack_vector", "av_weight", "exploitability_term", "remote"]},
 # "Network" appears only as ordinary prose, no vector named
 {"id": "network-prose-only",
  "query": "This bug is reachable over the network stack. What is the Attack Vector weight?",
  "truth": {},
  "expect_open": ["av_weight", "exploitability_term", "remote"]},
]
d = json.load(open(P))
have = {c["id"] for c in d["cases"]}
add = [c for c in NEW if c["id"] not in have]
if not add:
    print("all present"); raise SystemExit(0)
shutil.copy(P, P + ".bak3")
d["cases"].extend(add)
with open(P, "w") as f:
    json.dump(d, f, indent=2); f.write("\n")
print("added %d -> %d total" % (len(add), len(d["cases"])))
