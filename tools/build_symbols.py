"""Build a compact address -> label map from Il2CppInspector's metadata.json.

Output (tab-separated, one per line): <hex address>\t<kind>\t<label>
  kind: M = method code, G = generic method code, S = string literal,
        T = TypeInfo*, R = TypeRef, I = MethodInfo*, A = il2cpp API, E = export
Usage: python build_symbols.py dump/inspector/metadata.json dump/symbols.tsv
"""
import json
import sys

src, out = sys.argv[1], sys.argv[2]
am = json.load(open(src, encoding="utf-8"))["addressMap"]


def one_line(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")


rows = {}
for e in am["methodDefinitions"]:
    rows.setdefault(int(e["virtualAddress"], 16), ("M", f'{e["group"].split("/", 1)[-1]}::{e["dotNetSignature"]}'))
for e in am["constructedGenericMethods"]:
    rows.setdefault(int(e["virtualAddress"], 16), ("G", e["signature"]))
for e in am["stringLiterals"]:
    rows[int(e["virtualAddress"], 16)] = ("S", '"' + one_line(e["string"]) + '"')
for e in am["typeInfoPointers"]:
    rows[int(e["virtualAddress"], 16)] = ("T", f'typeof({e["dotNetType"]})')
for e in am["typeRefPointers"]:
    rows[int(e["virtualAddress"], 16)] = ("R", f'typeref({e["dotNetType"]})')
for e in am["methodInfoPointers"]:
    rows[int(e["virtualAddress"], 16)] = ("I", f'methodinfo({e["dotNetSignature"]} @ {e.get("methodAddress", "?")})')
for e in am["apis"]:
    rows.setdefault(int(e["virtualAddress"], 16), ("A", e["name"]))
for e in am["exports"]:
    rows.setdefault(int(e["virtualAddress"], 16), ("E", e["name"]))

with open(out, "w", encoding="utf-8") as f:
    for addr in sorted(rows):
        kind, label = rows[addr]
        f.write(f"{addr:X}\t{kind}\t{label}\n")
print(f"{len(rows)} symbols -> {out}")
