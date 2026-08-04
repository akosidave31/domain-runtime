# Pack Contract v0.2

The runtime is a domain-agnostic solver. A **pack** is the program it runs.
If runtime code ever needs to know a domain word, the contract has leaked.

Every rule below came from a measured failure. Numbers are from
`eval_runner.py` on `pack-pqc` with Qwen2.5-0.5B-Instruct.

## 0. The rule that matters most

**Never ask the model what the runtime can decide.**

Before a cell reaches the ask queue, the runtime tries to resolve it from a
law, from propagation, or from a literal match against the query. A model call
is the last resort, not the first.

This is not an optimisation. Removing one model call - binding `param_set` by
string match instead of asking - moved simulated-noise accuracy from 0.593
with 11 wrong answers to 1.000 with none. Anchor cells poison every value
derived from them, so the cheapest way to be right is not to ask.

Corollary: **verification and extraction are the same rule.** If the runtime
can check a value by matching it against the query, it can also obtain it that
way. Using the rule only to reject wastes half its power.

## 1. What the runtime guarantees a pack

- **Retrieval.** Knowledge chunked on `## ` headings, scored by IDF-weighted
  overlap, top-k injected as context. Empty retrieval is a legal outcome.
- **Cell instantiation** from `cells/schema.json`, per query.
- **Propagation to fixpoint** before any model call.
- **Literal binding** of query-scoped enum cells, before any model call.
- **Grammar-constrained decoding.** GBNF is generated from each cell spec, so
  invalid output cannot be produced. `null` is always legal.
- **Atomic proposals.** A proposal that binds cleanly but contradicts a law
  two steps later is rolled back entirely. Without this, the contradiction is
  logged while the corrupt value stays.
- **Literal grounding.** In question-only mode a proposed value must appear in
  the query. Numbers match on digit boundaries so "4" does not match inside
  "2048"; strings match as substrings, because a generic token-boundary rule
  broke hyphenated values like `ML-KEM-512`.
- **Cell-local retry**, max 2, of the failing cell only. A null is not a
  permanent verdict; if the network later advances, the cell is asked again.
- **Confirmation.** After convergence the runtime asks independently for cells
  the model did not supply and compares. A single root proposal leaves one
  path to every derived cell, so a wrong root propagates silently with nothing
  to contradict it. Confirmation cut silent errors from 14 to 1 at 30% noise.
- **Abstention.** An unresolved cell is reported unknown, never guessed. On
  conflict, `Result.trustworthy` is false and `Result.value()` returns None.

## 2. What a pack may NOT do

- **Ship executable code.** Laws are declarative data interpreted by a fixed
  set of forms. No `eval`, no `exec`, no imported pack modules. A new law form
  requires a runtime change and a `contract_version` bump. That friction is
  intended.
- **Ship grammars.** They are generated from cell specs. A static grammar
  cannot stay in sync with the schema.
- **Declare tools.** Tool trust is a runtime decision, never a remote pack's.
- **Reach the network at query time.**

## 3. Required files
cd ~/domain-runtime && cat >> CONTRACT.md << 'MDEOF'

## 3. Required files

    pack.json            id, version, contract_version, description
    routing.json         task-shaped profile: real questions, not prose
    prompt.md            framing, vocabulary, facts never to guess
    knowledge/*.md       corpus, chunked on '## ' headings
    cells/schema.json    cell definitions
    cells/laws.json      declarative laws
    eval/cases.json      held-out cases with expected values

validate_pack.py exits 0 or 1. No partial loads.

## 4. Cell spec

Fields: type (enum|int), range or values, scope, anchor, requires_anchor,
confirmable, askable, ask_cost, prompt.

**scope is the field most likely to be got wrong.** query means which thing
the question is about - it must come from the question, never from a chunk
that happens to describe something else. source means what the corpus states.
Conflating them is why a chunk about ML-KEM-512 got read as the subject of a
question about ML-KEM-2048.

**anchor marks the cell that identifies the subject.** Until it binds, no
requires_anchor cell can be attributed to anything. Every pack needs at least
one anchor.

**ask_cost is load-bearing.** It encodes which single question collapses the
most of the network - the difference between one model call and six.

**prompt must carry the question's vocabulary, not just the pack's.** A small
model does not know that "private key" and "decapsulation key" are the same
cell unless the prompt says so.

## 5. Law forms

- constant: cell = value
- table: key cell to a row of cells; identifying enables reverse lookup
- affine: target = a*source + b, bidirectional
- bilinear: target = scale * (sum of pairs + sum of plus), any single unknown

Four forms covered an entire domain. Resist growing this list until a second
pack proves it necessary. identifying columns must be unique across rows or
reverse lookup is silently ambiguous - the validator rejects this.

## 6. The model's only job

The model proposes cell values, one narrow question at a time. It never writes
the answer: prose is rendered from the solved network by render(), which
removes the drift surface entirely - a model cannot ramble inside a paragraph
it did not write.

## 7. Metrics

- extraction accuracy: expected values correct
- abstention accuracy: cells that should stay open, did
- silent errors: wrong, and nothing flagged it
- propagation ratio: derived / bound - work the model could not get wrong
- model calls / query: cost, and thermal budget on a phone

**Silent errors is the one that matters.** A wrong answer the system flags is
a different product from a wrong answer it ships. Everything else is
negotiable; this stays at zero.

The **oracle run is a gate**: eval_runner.py <pack> with no --llm must score
1.000/1.000. It is the ceiling with a perfect proposer, so anything below
means the runtime is broken, not the model. Two plausible-sounding changes
were caught this way within seconds of being written.

Current pack-pqc with Qwen2.5-0.5B: extraction 0.900, abstention 1.000,
ratio 0.948, silent 0.

## 8. Version

Packs declare contract_version. A mismatch is refused loudly rather than
half-loaded. Bump on any change to sections 3-5.

v0.2: added scope, anchor, requires_anchor, confirmable; removed grammar/ as
a required directory; added the section 0 rule.
