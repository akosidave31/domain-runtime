import json, shutil
P = "../pack-cvss/eval/cases.json"
NEW = [
 {"id": "adjacent-naming-trap",
  "query": "What is the CVSS 3.1 weight for Attack Vector Adjacent Network?",
  "truth": {"attack_vector": "Adjacent", "av_weight": 0.62},
  "expect": {"av_weight": 0.62, "exploitability_term": 5.0964, "remote": "no"}},
 {"id": "reverse-local-weight",
  "query": "A vulnerability has an Attack Vector weight of 0.55. Is it remotely exploitable?",
  "truth": {"av_weight": 0.55, "attack_vector": "Local", "remote": "no"},
  "expect": {"attack_vector": "Local", "exploitability_term": 4.521, "remote": "no"}},
 {"id": "physical-weight",
  "query": "What is the CVSS 3.1 weight for Attack Vector Physical?",
  "truth": {"attack_vector": "Physical", "av_weight": 0.20},
  "expect": {"av_weight": 0.2, "exploitability_term": 1.644, "remote": "no"}},
 {"id": "vector-unstated-abstain",
  "query": "What is the Attack Vector weight for this vulnerability?",
  "truth": {},
  "expect_open": ["av_weight", "exploitability_term", "remote"]},
]
d = json.load(open(P))
have = {c["id"] for c in d["cases"]}
add = [c for c in NEW if c["id"] not in have]
if not add:
    print("all 4 already present"); raise SystemExit(0)
shutil.copy(P, P + ".bak")
d["cases"].extend(add)
json.dump(d, open(P, "w"), indent=2)
print("added %d -> %d cases total" % (len(add), len(d["cases"])))
