#!/usr/bin/env python3
"""llm.py - proposer backed by llama-server. stdlib only."""
import json, sys, urllib.error, urllib.request

ENDPOINT = "http://127.0.0.1:8080"


def gbnf(spec):
    if spec.get("type") == "enum":
        alts = " | ".join('"\\"%s\\""' % v for v in spec["values"])
        val = f"({alts} | \"null\")"
    else:
        val = '([0-9]+ | "null")'
    return (
        'root ::= "{" ws "\\"value\\"" ws ":" ws value ws "," ws '
        '"\\"confidence\\"" ws ":" ws conf ws "}"\n'
        f'value ::= {val}\n'
        'conf ::= "0." [0-9]+ | "1.0" | "0" | "1"\n'
        'ws ::= [ \\t\\n]*\n'
    )


def build_prompt(context, query, cell, spec):
    ask = spec.get("prompt") or f"What is {cell}?"
    if spec.get("type") == "enum":
        allowed = "One of: " + ", ".join(map(str, spec["values"])) + ", or null."
    else:
        lo, hi = spec.get("range", ["?", "?"])
        allowed = f"An integer between {lo} and {hi}, or null."
    system = ("You extract a single value from the SOURCE below. "
              "Answer only from the SOURCE. If the SOURCE does not state the "
              "value, answer null. Never guess, never calculate from memory, "
              "never use knowledge outside the SOURCE. Answering null is "
              "correct and expected when the value is absent.")
    user = (f"SOURCE:\n{context}\n\nUSER QUESTION: {query}\n\n"
            f"EXTRACT: {ask}\nALLOWED: {allowed}\n\nReply with JSON only.")
    return (f"<|im_start|>system\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n")


def call(prompt, grammar, endpoint=ENDPOINT, timeout=180):
    body = json.dumps({"prompt": prompt, "grammar": grammar, "n_predict": 64,
                       "temperature": 0.0, "cache_prompt": True,
                       "stop": ["<|im_end|>"]}).encode()
    req = urllib.request.Request(endpoint.rstrip("/") + "/completion",
                                 data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["content"]


def make_proposer(context, endpoint=ENDPOINT, verbose=False):
    def propose(cell, spec, query):
        try:
            raw = call(build_prompt(context, query, cell, spec), gbnf(spec), endpoint)
        except urllib.error.URLError as e:
            raise SystemExit(f"cannot reach llama-server at {endpoint}: {e}")
        try:
            obj = json.loads(raw.strip())
        except json.JSONDecodeError:
            if verbose:
                print(f"    [{cell}] unparseable: {raw!r}")
            return None
        v = obj.get("value")
        if verbose:
            print(f"    [{cell}] -> {v!r} conf={obj.get('confidence')}")
        if v is None:
            return None
        if spec.get("type") == "int":
            try:
                return int(v)
            except (TypeError, ValueError):
                return None
        return v
    return propose


def smoke(endpoint=ENDPOINT):
    ctx = ("ML-KEM-768 has module rank k = 3. Its encapsulation key is 1184 "
           "bytes and its ciphertext is 1088 bytes.")
    checks = [
        ("param_set", {"type": "enum",
                       "values": ["ML-KEM-512", "ML-KEM-768", "ML-KEM-1024"],
                       "prompt": "Which ML-KEM parameter set?"},
         "What parameter set is described?", "ML-KEM-768"),
        ("k", {"type": "int", "range": [2, 4], "prompt": "Module rank k?"},
         "What is k?", 3),
        ("dk_bytes", {"type": "int", "range": [1, 100000],
                      "prompt": "Decapsulation key size in bytes?"},
         "What is the private key size?", None),
    ]
    p = make_proposer(ctx, endpoint, verbose=True)
    print(f"llama-server: {endpoint}\n")
    ok = 0
    for cell, spec, q, want in checks:
        got = p(cell, spec, q)
        good = got == want
        ok += good
        note = "" if want is not None else "   <- must be None: not in SOURCE"
        print(f"  {'PASS' if good else 'FAIL'}  {cell:<12} got {got!r}, want {want!r}{note}")
    print(f"\n{ok}/{len(checks)} passed")
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    ep = sys.argv[sys.argv.index("--endpoint") + 1] if "--endpoint" in sys.argv else ENDPOINT
    if "--smoke" in sys.argv:
        sys.exit(smoke(ep))
    print(__doc__)
