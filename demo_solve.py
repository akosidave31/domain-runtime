"""
Proves the thesis before any model is wired up.

Run:  python demo_solve.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from cells.engine import Network, Contradiction

PACK = os.path.join(os.path.dirname(__file__), "..", "pack-pqc", "cells")
schema = json.load(open(os.path.join(PACK, "schema.json")))
laws = json.load(open(os.path.join(PACK, "laws.json")))["laws"]


def banner(t):
    print(f"\n{'=' * 62}\n{t}\n{'=' * 62}")


# ---------------------------------------------------------------- case 1
banner("CASE 1  one proposal, everything else derived")

net = Network(schema, laws)
net.propagate()
print("before any model call:")
print(net.trace())

print("\n>> model proposes: param_set = 'ML-KEM-768'  (chunk pqc-003, conf 0.91)")
net.propose("param_set", "ML-KEM-768", chunk_id="pqc-003", confidence=0.91)
net.propagate()

print(net.trace())
print("\nstats:", net.stats())


# ---------------------------------------------------------------- case 2
banner("CASE 2  reverse propagation: model knows only a byte count")

net2 = Network(schema, laws)
net2.propagate()
print(">> model proposes: ek_bytes = 1568  (chunk pqc-011, conf 0.77)")
net2.propose("ek_bytes", 1568, chunk_id="pqc-011", confidence=0.77)
net2.propagate()
print(net2.trace())
print("\nstats:", net2.stats())


# ---------------------------------------------------------------- case 3
banner("CASE 3  contradiction caught -> cell-local re-ask")

net3 = Network(schema, laws)
net3.propose("param_set", "ML-KEM-768", chunk_id="pqc-003", confidence=0.91)
net3.propagate()
print(">> model proposes: ct_bytes = 1568   (wrong - that is ML-KEM-1024's)")
try:
    net3.propose("ct_bytes", 1568, chunk_id="pqc-007", confidence=0.55)
except Contradiction as e:
    print(f"   CONTRADICTION: {e}")
    print("   -> re-ask ONLY ct_bytes. The other 8 cells stay bound.")
    print(f"   -> already-derived value stands: ct_bytes = {net3.cells['ct_bytes'].value}")

print("\nstats:", net3.stats())


# ---------------------------------------------------------------- case 4
banner("CASE 4  what would the model be asked next, if anything?")

net4 = Network(schema, laws)
net4.propagate()
print("open cells, cheapest to ask first:", net4.askable()[:3])
print("-> controller asks 'param_set' (ask_cost 1), not 'du' (ask_cost 60).")
print("   One well-chosen question collapses the whole network.")
