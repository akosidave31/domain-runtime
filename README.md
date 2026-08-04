# domain-runtime

Runs pluggable domain packs. Contains no domain knowledge itself —
in the sense of "container runtime," not "containerized."
The domain lives in the pack.

Small model + pack + constraint propagation. The model proposes cell
values; the network holds the answer. See CONTRACT.md.

    python demo_solve.py

ML-KEM slice: 8 of 9 cells derived from one proposal (ratio 0.889).
