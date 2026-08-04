#!/usr/bin/env python3
"""retrieve.py - chunks pack knowledge and picks what a query needs.
Lexical IDF-weighted overlap, stdlib only. A semantic scorer can replace
score() later without changing the interface.

    python retrieve.py ../pack-pqc "ciphertext size of ML-KEM-768"
"""
import glob, math, os, re, sys
from collections import Counter

STOP = {"a","an","and","are","as","at","be","by","for","from","has","have",
        "in","is","it","its","of","on","or","that","the","to","was","what",
        "which","with","how","does","do","give","many","much","this","these",
        "those","there","size","value"}
TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def tokenize(text):
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP]


def chunk_file(path):
    raw = open(path).read()
    base = os.path.splitext(os.path.basename(path))[0]
    parts, cur, title = [], [], "preamble"
    for line in raw.splitlines():
        if line.startswith("## "):
            if any(l.strip() for l in cur):
                parts.append((title, "\n".join(cur).strip()))
            title, cur = line[3:].strip(), [line]
        else:
            cur.append(line)
    if any(l.strip() for l in cur):
        parts.append((title, "\n".join(cur).strip()))
    return [{"id": f"{base}#{i}", "title": t, "text": x}
            for i, (t, x) in enumerate(parts)]


def load_chunks(pack):
    out = []
    for f in sorted(glob.glob(os.path.join(pack, "knowledge", "*.md"))):
        out.extend(chunk_file(f))
    if not out:
        raise SystemExit(f"no knowledge/*.md in {pack}")
    return out


def build_index(chunks):
    df = Counter()
    for c in chunks:
        c["tokens"] = tokenize(c["title"] + " " + c["text"])
        df.update(set(c["tokens"]))
    n = len(chunks)
    return {t: math.log(1 + n / (1 + d)) for t, d in df.items()}


def score(query, chunks, idf):
    q = Counter(tokenize(query))
    scored = []
    for c in chunks:
        tf = Counter(c["tokens"])
        s = 0.0
        for t, qn in q.items():
            if t in tf:
                s += idf.get(t, 0.0) * qn * (1 + math.log(tf[t]))
        title_toks = set(tokenize(c["title"]))
        s += 2.0 * sum(idf.get(t, 0.0) for t in q if t in title_toks)
        scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    return scored


def retrieve(chunks, idf, query, k=2, min_score=0.1):
    return [(s, c) for s, c in score(query, chunks, idf)[:k] if s >= min_score]


def context_for(chunks, idf, query, k=2):
    hits = retrieve(chunks, idf, query, k)
    return "\n\n".join(c["text"] for _, c in hits) if hits else ""


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    pack, query = sys.argv[1], " ".join(sys.argv[2:])
    chunks = load_chunks(pack)
    idf = build_index(chunks)
    print(f"{len(chunks)} chunks\n")
    for s, c in score(query, chunks, idf)[:5]:
        print(f"{'->' if s >= 0.1 else '  '} {s:6.2f}  {c['id']:<28} {c['title']}")
