import json, shutil
P = "../pack-cvss/eval/cases.json"
NEW = [
 # one in-range number, cue adjacent -- must bind with no model call
 {"id": "numeric-lone-inrange",
  "query": "The Attack Vector weight is 0.62. Which vector is that?",
  "truth": {"av_weight": 0.62, "attack_vector": "Adjacent"},
  "expect": {"attack_vector": "Adjacent", "exploitability_term": 5.0964, "remote": "no"}},
 # two in-range numbers -- ambiguous, must abstain
 {"id": "numeric-two-inrange",
  "query": "Is the Attack Vector weight 0.55 or 0.62 for this one?",
  "truth": {},
  "expect_open": ["av_weight", "attack_vector", "exploitability_term", "remote"]},
 # a number present but outside range -- must not bind
 {"id": "numeric-out-of-range",
  "query": "CVSS 3.1 defines four vectors. What is the Attack Vector weight?",
  "truth": {},
  "expect_open": ["av_weight", "exploitability_term", "remote"]},
]
d = json.load(open(P))
have = {c["id"] for c in d["cases"]}
add = [c for c in NEW if c["id"] not in have]
if not add:
    print("all present"); raise SystemExit(0)
shutil.copy(P, P + ".bak4")
d["cases"].extend(add)
with open(P, "w") as f:
    json.dump(d, f, indent=2); f.write("\n")
print("added %d -> %d total" % (len(add), len(d["cases"])))
