#!/usr/bin/env python3
"""validate_pack.py - enforces CONTRACT.md. Exit 0 = loads, 1 = refused."""
import json, os, sys

CV = "0.1"
FORMS = {"constant", "table", "affine", "bilinear"}
TYPES = {"int", "enum"}
E, W = [], []


def load(p, n):
    if not os.path.exists(p):
        E.append(f"missing: {n}"); return None
    try:
        return json.load(open(p))
    except json.JSONDecodeError as x:
        E.append(f"{n}: bad JSON line {x.lineno}: {x.msg}"); return None


def val_ok(loc, cell, v, cells):
    s = cells[cell]
    if s.get("type") == "enum" and v not in s.get("values", []):
        E.append(f"{loc}: {v!r} not in enum of {cell!r}")
    elif s.get("type") == "int":
        if not isinstance(v, int):
            E.append(f"{loc}: {v!r} for {cell!r} must be int")
        else:
            r = s.get("range")
            if isinstance(r, list) and len(r) == 2 and not (r[0] <= v <= r[1]):
                E.append(f"{loc}: {v} for {cell!r} outside {r}")


def check_schema(sch):
    if not isinstance(sch, dict) or not isinstance(sch.get("cells"), dict) or not sch["cells"]:
        E.append("schema.json: need non-empty 'cells' object"); return {}
    for n, s in sch["cells"].items():
        L = f"cell {n!r}"
        if not isinstance(s, dict):
            E.append(f"{L}: spec must be object"); continue
        t = s.get("type")
        if t not in TYPES:
            E.append(f"{L}: type must be {sorted(TYPES)}, got {t!r}"); continue
        if t == "enum":
            v = s.get("values")
            if not isinstance(v, list) or not v:
                E.append(f"{L}: enum needs non-empty 'values'")
            elif len(set(map(str, v))) != len(v):
                E.append(f"{L}: duplicate values")
        if t == "int":
            r = s.get("range")
            if not (isinstance(r, list) and len(r) == 2 and all(isinstance(x, int) for x in r)):
                E.append(f"{L}: int needs 'range':[lo,hi] ints")
            elif r[0] > r[1]:
                E.append(f"{L}: range lo>hi")
        sc = s.get("scope")
        if sc is not None and sc not in ("query", "source"):
            E.append(f"{L}: scope must be 'query' or 'source', got {sc!r}")
        if sc == "query" and t != "enum":
            W.append(f"{L}: scope 'query' only binds literally for enum cells; "
                     f"an int cell will fall through to the model")
        for flag in ("anchor", "requires_anchor", "confirmable"):
            if flag in s and not isinstance(s[flag], bool):
                E.append(f"{L}: '{flag}' must be true or false")
        if s.get("anchor") and sc != "query":
            W.append(f"{L}: anchor cells are normally scope 'query' - an "
                     f"anchor read from the source cannot identify the subject")

        a = s.get("askable", True)
        if not isinstance(a, bool):
            E.append(f"{L}: 'askable' must be bool")
        elif a:
            if "ask_cost" not in s:
                W.append(f"{L}: askable, no ask_cost - sorts last")
            elif not isinstance(s["ask_cost"], int):
                E.append(f"{L}: ask_cost must be int")
            if not s.get("prompt"):
                E.append(f"{L}: askable needs 'prompt'")
    anchors = [n for n, c in sch["cells"].items()
               if isinstance(c, dict) and c.get("anchor")]
    needs = [n for n, c in sch["cells"].items()
             if isinstance(c, dict) and c.get("requires_anchor")]
    if needs and not anchors:
        E.append(f"cells {sorted(needs)} declare requires_anchor but no cell "
                 f"declares anchor: true - they can never be asked in source "
                 f"mode and will never resolve")
    return sch["cells"]


def check_laws(doc, cells):
    laws = doc.get("laws")
    if not isinstance(laws, list):
        E.append("laws.json: 'laws' must be a list"); return
    seen = set()
    for i, w in enumerate(laws):
        L = f"laws[{i}]"
        if not isinstance(w, dict):
            E.append(f"{L}: must be object"); continue
        lid = w.get("id")
        if not lid:
            E.append(f"{L}: needs 'id'")
        elif lid in seen:
            E.append(f"{L}: duplicate id {lid!r}")
        else:
            seen.add(lid)
        L = f"law {lid!r}" if lid else L
        f = w.get("form")
        if f not in FORMS:
            E.append(f"{L}: unknown form {f!r}. Known {sorted(FORMS)}. New forms "
                     f"need a runtime change + contract bump; packs ship no code.")
            continue

        def ref(n, fld):
            if n not in cells:
                E.append(f"{L}: {fld} references undefined cell {n!r}"); return False
            return True

        if f == "constant":
            if "cell" not in w or "value" not in w:
                E.append(f"{L}: needs 'cell' and 'value'")
            elif ref(w["cell"], "cell"):
                val_ok(L, w["cell"], w["value"], cells)

        elif f == "affine":
            for k in ("target", "source", "a", "b"):
                if k not in w:
                    E.append(f"{L}: affine needs {k!r}")
            if "target" in w and "source" in w:
                ref(w["target"], "target"); ref(w["source"], "source")
                if w["target"] == w["source"]:
                    E.append(f"{L}: target and source identical")
            if w.get("a") == 0:
                E.append(f"{L}: 'a' cannot be 0 - not invertible")
            for k in ("a", "b"):
                if k in w and not isinstance(w[k], int):
                    E.append(f"{L}: {k!r} must be int (floats break exact propagation)")

        elif f == "table":
            key, rows = w.get("key"), w.get("rows")
            if not key or not isinstance(rows, dict) or not rows:
                E.append(f"{L}: needs 'key' and non-empty 'rows'"); continue
            if not ref(key, "key"):
                continue
            ks = cells[key]
            if ks.get("type") == "enum":
                dec = set(map(str, ks.get("values", [])))
                if set(rows) - dec:
                    E.append(f"{L}: rows not in enum: {sorted(set(rows)-dec)}")
                if dec - set(rows):
                    W.append(f"{L}: no row for {sorted(dec-set(rows))} - won't propagate")
            for rk, row in rows.items():
                if not isinstance(row, dict):
                    E.append(f"{L}: row {rk!r} must be object"); continue
                for c, v in row.items():
                    if ref(c, f"row {rk!r}"):
                        val_ok(f"{L} row {rk!r}", c, v, cells)
            for c in w.get("identifying", []):
                if ref(c, "identifying"):
                    vs = [r.get(c) for r in rows.values()]
                    if len(set(map(str, vs))) != len(vs):
                        E.append(f"{L}: identifying {c!r} not unique - reverse "
                                 f"lookup ambiguous")

        elif f == "bilinear":
            if "target" not in w or "scale" not in w:
                E.append(f"{L}: needs 'target' and 'scale'")
            else:
                ref(w["target"], "target")
                if not isinstance(w["scale"], int) or w["scale"] == 0:
                    E.append(f"{L}: 'scale' must be non-zero int")
            for p in w.get("terms", []):
                if isinstance(p, list) and len(p) == 2:
                    for n in p:
                        ref(n, "terms")
                else:
                    E.append(f"{L}: each 'terms' entry must be a pair")
            for n in w.get("plus", []):
                ref(n, "plus")
            if not w.get("terms") and not w.get("plus"):
                E.append(f"{L}: has neither 'terms' nor 'plus'")

    touched = set()
    for w in laws:
        if not isinstance(w, dict):
            continue
        for k in ("cell", "target", "source", "key"):
            if isinstance(w.get(k), str):
                touched.add(w[k])
        for r in (w.get("rows") or {}).values():
            if isinstance(r, dict):
                touched.update(r)
        for p in w.get("terms", []):
            if isinstance(p, list):
                touched.update(x for x in p if isinstance(x, str))
        touched.update(w.get("plus", [])); touched.update(w.get("identifying", []))
    for n, s in cells.items():
        if n not in touched and not s.get("askable", True):
            E.append(f"cell {n!r} unreachable: no law binds it, askable false")


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    only = "--cells" in sys.argv
    if not a:
        print(__doc__); return 2
    pk = os.path.abspath(a[0])
    if not os.path.isdir(pk):
        print(f"REFUSED {pk}: not a directory"); return 1

    if not only:
        for r in ("pack.json", "routing.json", "prompt.md"):
            if not os.path.exists(os.path.join(pk, r)):
                E.append(f"missing required file: {r}")
        for d in ("knowledge", "eval"):
            p = os.path.join(pk, d)
            if not os.path.isdir(p):
                E.append(f"missing required dir: {d}/")
            elif not os.listdir(p):
                E.append(f"empty required dir: {d}/")
        mp = os.path.join(pk, "pack.json")
        m = load(mp, "pack.json") if os.path.exists(mp) else None
        if m:
            if m.get("contract_version") is None:
                E.append("pack.json: missing contract_version")
            elif str(m["contract_version"]) != CV:
                E.append(f"pack.json: contract_version {m['contract_version']!r} "
                         f"but runtime implements {CV!r} - refusing")
            if not m.get("id"):
                E.append("pack.json: missing 'id'")

    sch = load(os.path.join(pk, "cells/schema.json"), "cells/schema.json")
    lw = load(os.path.join(pk, "cells/laws.json"), "cells/laws.json")
    cells = check_schema(sch) if sch else {}
    if lw and cells:
        check_laws(lw, cells)

    print(f"pack: {os.path.basename(pk)}" + ("   [--cells]" if only else ""))
    print(f"cells: {len(cells)}   laws: {len(lw.get('laws', [])) if lw else 0}")
    for x in W:
        print(f"  warn   {x}")
    for x in E:
        print(f"  ERROR  {x}")
    print("\n" + (f"REFUSED  {len(E)} error(s)" if E else f"OK  {len(W)} warning(s)"))
    return 1 if E else 0


if __name__ == "__main__":
    sys.exit(main())
