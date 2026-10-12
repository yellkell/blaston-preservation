"""Annotate a Cpp2IL ISIL dump file: append resolved symbols/strings to every hex address.

Usage: python annotate_isil.py dump/symbols.tsv <isil .txt file> [more files...]
Writes <file>.annotated.txt next to each input (or prints to stdout with --stdout).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from isil_addrs import AddrExtractor  # noqa: E402


def load(path):
    syms = {}
    for line in open(path, encoding="utf-8"):
        addr, kind, label = line.rstrip("\n").split("\t", 2)
        syms[int(addr, 16)] = (kind, label)
    return syms


def annotate(lines, syms):
    addrs = AddrExtractor()
    for line in lines:
        if line.startswith("Method: "):
            addrs.reset()
        notes = []
        for a in addrs(line):
            hit = syms.get(a)
            if hit:
                notes.append(f"{hit[0]}:{hit[1]}")
        yield line.rstrip("\n") + (("    ; " + " | ".join(notes)) if notes else "")


def main():
    args = sys.argv[1:]
    to_stdout = "--stdout" in args
    args = [a for a in args if a != "--stdout"]
    syms = load(args[0])
    for path in args[1:]:
        out = list(annotate(open(path, encoding="utf-8", errors="replace"), syms))
        if to_stdout:
            print("\n".join(out))
        else:
            dst = path[:-4] + ".annotated.txt" if path.endswith(".txt") else path + ".annotated"
            open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")
            print(dst)


if __name__ == "__main__":
    main()
