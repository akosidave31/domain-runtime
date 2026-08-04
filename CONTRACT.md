# Pack Contract v0.1

The runtime is a domain-agnostic solver. A **pack** is the program it runs.
This file is the interface between them. If runtime code ever needs to know a
domain word, the contract has leaked and this file is wrong.

---

## 1. What the runtime guarantees a pack

- **Routing.** Cosine similarity over the pack's `routing.json` profile.
- **Retrieval.** Top-k chunks from `knowledge/` injected as context.
- **Cell instantiation.** `cells/schema.json` becomes a live network per query.
- **Propagation to fixpoint.** Every value derivable without the model is derived
  before the model is asked anything.
- **Grammar-constrained decoding.** The model physically cannot emit output
  violating `grammar/*.gbnf`.
- **Contradiction detection.** Any proposal conflicting with a bound cell is
  rejected with the violating cell named.
- **Bounded cell-local retry.** Max 2 re-asks, of the failing cell only.
- **Abstention.** A cell that cannot be resolved is reported as unknown. It is
  never guessed.

## 2. What a pack may NOT do

- **Ship executable code.** Laws and constraints are declarative data. The
  engine interprets a fixed set of forms. There is no `eval`, no `exec`, no
  import of pack modules. A pack that needs a new law form requires a runtime
  change and a `contract_version` bump — that is the intended friction.
- **Declare tools.** Tool trust is a runtime/source-level decision, never a
  remote pack's.
- **Reach the network at query time.**

---

## 3. Required files

```
pack.json            id, version, contract_version
routing.json         task-shaped profile (actual questions, not prose)
prompt.md            framing + facts the model must never guess
knowledge/*.md       chunked corpus
cells/schema.json    cell definitions
cells/laws.json      declarative laws
grammar/*.gbnf       output shapes
eval/                held-out Q&A + expected values
```

`validate_pack.py` exits 0 or 1. No partial loads.

---

## 4. Cell spec

```json
"ek_bytes": {
  "type": "int",              // enum | int
  "range": [1, 100000],       // int only
  "values": [...],            // enum only
  "askable": true,            // may the model be asked for this?
  "ask_cost": 20,             // lower = asked first
  "prompt": "..."             // the narrow question posed to the model
}
```

`ask_cost` is load-bearing. It encodes which single question collapses the most
of the network. Ordering by it is the difference between one model call and six.

## 5. Law forms (v0.1)

| form | shape | direction |
|---|---|---|
| `constant` | `cell = value` | — |
| `table` | key cell → row of cells; `identifying` columns enable reverse lookup | both |
| `affine` | `target = a*source + b` | both |
| `bilinear` | `target = scale * (Σ pairs + Σ plus)` | solves any single unknown |

Adding a form is a runtime change. Four forms covered the whole ML-KEM slice;
resist growing this list until a second pack proves it necessary.

---

## 6. The model's only job

The model does not write answers. It **proposes cell values**, one narrow
question at a time, and every proposal carries provenance:

```
{ "value": ..., "chunk_id": "...", "confidence": 0.0-1.0 }
```

Enforced by grammar. `chunk_id` becomes the justification link in the truth
maintenance system; `confidence` feeds trust-weighted conflict resolution.
Final prose is rendered from the solved network by template — the model never
writes the paragraph, so it cannot drift inside one.

---

## 7. The metric

`propagation_ratio` = derived cells / bound cells.

Accuracy is the headline number, but this is the one that says whether the
architecture is working. Every point of ratio is a model call that could not
have been wrong. Track it per pack, per query class.

Current `pack-pqc` ML-KEM slice: **0.889** — one proposal, eight derivations.

---

## 8. Version

Packs declare `contract_version`. The runtime refuses a mismatch loudly rather
than half-loading. Bump on any change to sections 3–5.
