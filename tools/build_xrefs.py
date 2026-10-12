"""Scan a Cpp2IL ISIL dump and build cross-reference indexes using dump/symbols.tsv.

Outputs (in <out_dir>):
  string_xrefs.tsv   "<literal>"\t<file>::<method>     — which methods use which string literal
  call_xrefs.tsv     <callee>\t<file>::<method>         — which methods call which method
Optionally (--annotate <path-substring>[,...]) writes .annotated.txt copies of matching ISIL files.

Usage: python build_xrefs.py dump/symbols.tsv dump/isil/IsilDump dump/xrefs [--annotate Fidelity,RGCommon]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from isil_addrs import AddrExtractor  # noqa: E402


def main():
    args = sys.argv[1:]
    annotate = []
    if "--annotate" in args:
        i = args.index("--annotate")
        annotate = args[i + 1].split(",")
        del args[i: i + 2]
    sym_path, isil_root, out_dir = args
    os.makedirs(out_dir, exist_ok=True)

    syms = {}
    for line in open(sym_path, encoding="utf-8"):
        a, k, label = line.rstrip("\n").split("\t", 2)
        syms[int(a, 16)] = (k, label)

    sx = open(os.path.join(out_dir, "string_xrefs.tsv"), "w", encoding="utf-8")
    cx = open(os.path.join(out_dir, "call_xrefs.tsv"), "w", encoding="utf-8")
    n_files = 0
    for root, _, files in os.walk(isil_root):
        for fn in files:
            if not fn.endswith(".txt") or fn.endswith(".annotated.txt"):
                continue
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, isil_root)[:-4].replace(os.sep, "/")
            if os.name == "nt":  # allow >260-char paths
                path = "\\\\?\\" + os.path.abspath(path)
            want_annot = any(s in rel for s in annotate)
            out_lines = [] if want_annot else None
            method = "?"
            seen = set()
            addrs = AddrExtractor()
            for line in open(path, encoding="utf-8", errors="replace"):
                if line.startswith("Method: "):
                    method = line[8:].strip()
                    seen = set()
                    addrs.reset()
                notes = []
                for a in addrs(line):
                    hit = syms.get(a)
                    if not hit:
                        continue
                    kind, label = hit
                    notes.append(f"{kind}:{label}")
                    key = (kind, label)
                    if key in seen:
                        continue
                    seen.add(key)
                    if kind == "S":
                        sx.write(f"{label}\t{rel}::{method}\n")
                    elif kind in "MG" and ("call" in line or "BL " in line or " Call " in line):
                        cx.write(f"{label}\t{rel}::{method}\n")
                if out_lines is not None:
                    out_lines.append(line.rstrip("\n") + (("    ; " + " | ".join(notes)) if notes else ""))
            if out_lines is not None:
                with open(path[:-4] + ".annotated.txt", "w", encoding="utf-8") as f:
                    f.write("\n".join(out_lines) + "\n")
            n_files += 1
    print(f"scanned {n_files} ISIL files -> {out_dir}")


if __name__ == "__main__":
    main()
