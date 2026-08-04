#!/usr/bin/env python3
"""router.py - picks which pack a query belongs to.

    python router.py sources.json "ciphertext size of ML-KEM-768"

Lexical, reusing retrieve.py's scorer. Embedding routing is an upgrade to
make when this measurably fails, not before - per CONTRACT section 0, the
runtime should not reach for a model to decide what string matching decides.

Two outputs matter equally: which pack when one fits, and NO pack when none
does. A runtime that routes every query somewhere will confidently answer
questions no pack covers.
"""
import json
import math
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from retrieve import tokenize

MIN_SCORE = 3.0   # calibrated at 1 and 3 packs: lowest pos 3.75, highest neg 2.38
MARGIN = 1.25


def load_profiles(pack_dirs):
    profiles = []
    for d in pack_dirs:
        path = os.path.join(d, "routing.json")
        if not os.path.exists(path):
            continue
        r = json.load(open(path))
        # weight by specificity: keywords name the domain, questions show its
        # shape, the description is the vaguest of the three
        weighted = (" ".join(r.get("keywords", [])) * 3
                    + " " + " ".join(r.get("questions", [])) * 2
                    + " " + r.get("description_for_router", ""))
        profiles.append({
            "id": r.get("id") or os.path.basename(d),
            "dir": d,
            "tokens": Counter(tokenize(weighted)),
            "vocab": set(tokenize(weighted)),
        })
    if not profiles:
        raise SystemExit("no packs with routing.json found")
    return profiles


def build_idf(profiles):
    """A term known to one pack is evidence. A term known to all is not.

    Normalised so a maximally distinctive term is always worth 1.0 regardless
    of how many packs are loaded. Without this the raw IDF scale grows with
    pack count, and a threshold calibrated on three packs silently rejects
    valid queries when only one is installed.
    """
    n = len(profiles)
    df = Counter()
    for p in profiles:
        df.update(p["vocab"])
    top = math.log(1 + n)
    return {t: math.log(1 + n / d) / top for t, d in df.items()}


def score(query, profiles, idf=None):
    """Distinctiveness-weighted overlap, softened by coverage.

    Coverage alone killed short queries carrying one strong signal: "Tell me
    about Kyber" is unambiguous, but three filler words dropped it below
    threshold. Coverage now scales between 0.5x and 1x rather than to zero.
    """
    q = tokenize(query)
    if not q:
        return [(0.0, p) for p in profiles]
    if idf is None:
        idf = build_idf(profiles)
    out = []
    for p in profiles:
        hits = sum(1 for t in q if t in p["vocab"])
        weight = sum(idf.get(t, 0.0) * min(p["tokens"].get(t, 0), 6) for t in q)
        out.append((weight * (0.5 + 0.5 * hits / len(q)), p))
    out.sort(key=lambda x: -x[0])
    return out


def route(query, profiles, min_score=MIN_SCORE, margin=MARGIN):
    """Returns (pack | None, reason, scored)."""
    scored = score(query, profiles)
    top_score, top = scored[0]
    if top_score < min_score:
        return None, f"no pack scored above {min_score} (best {top_score:.1f})", scored
    if len(scored) > 1:
        second = scored[1][0]
        if second > 0 and top_score / second < margin:
            return None, (f"ambiguous: {top['id']} {top_score:.1f} vs "
                          f"{scored[1][1]['id']} {second:.1f}"), scored
    return top, f"score {top_score:.1f}", scored


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    src, query = sys.argv[1], " ".join(sys.argv[2:])
    dirs = json.load(open(src))["packs"] if src.endswith(".json") else [src]
    profiles = load_profiles(dirs)
    pack, reason, scored = route(query, profiles)
    print(f"query: {query}")
    for s, p in scored[:4]:
        print(f"   {s:7.2f}  {p['id']}")
    print(f"-> {pack['id'] if pack else 'ABSTAIN'}   ({reason})")
