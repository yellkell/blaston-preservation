"""Annotate Ghidra C output: append what each DAT_<addr> global really is.

ARM64 IL2CPP code reaches string literals / TypeInfo / MethodInfo through GOT slots, which Ghidra prints as
DAT_<slot>. Using the ELF relocations (slot -> target) and dump-quest/symbols.tsv (target -> label) we turn
    Application_OpenURL(DAT_057e7348, ...)
into
    Application_OpenURL(DAT_057e7348/*"https://…"*/, ...)

Usage: python annotate_decompiled.py <libil2cpp.so> <symbols.tsv> <decompiled_dir>   (rewrites files in place)
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from add_got_symbols import relative_relocs  # noqa: E402

GHIDRA_RELOC_SKEW = 0x100000
DAT = re.compile(r"(?<![0-9A-Za-z])(?:PTR_)?DAT_([0-9a-fA-F]{6,16})\b(?!/\*)")


def short(kind, label):
    if kind == "S":
        s = label if len(label) <= 80 else label[:77] + '…"'
        return s.replace("*/", "*\\/")
    return label.replace("*/", "*\\/")[:100]


def main():
    so, sym_path, root = sys.argv[1:4]
    syms = {}
    for line in open(sym_path, encoding="utf-8"):
        a, k, label = line.rstrip("\n").split("\t", 2)
        syms[int(a, 16)] = (k, label)
    got = {slot: tgt for slot, tgt in relative_relocs(so) if tgt in syms}
    files = changed = 0
    for dirpath, _, names in os.walk(root):
        for n in names:
            if not n.endswith(".c"):
                continue
            p = os.path.join(dirpath, n)
            if os.name == "nt":  # some generic-type file names exceed MAX_PATH
                p = "\\\\?\\" + os.path.abspath(p)
            text = open(p, encoding="utf-8").read()

            def sub(m):
                addr = int(m.group(1), 16)
                # Ghidra applied ELF relocations at its default image base 0x100000 before we re-based to 0,
                # so pointer values (and the DAT_ labels derived from them) are +0x100000 off.
                hit = (syms.get(addr - GHIDRA_RELOC_SKEW) or syms.get(addr)
                       or (syms[got[addr]] if addr in got else None))
                return m.group(0) + (f"/*{short(*hit)}*/" if hit else "")

            new = DAT.sub(sub, text)
            files += 1
            if new != text:
                changed += 1
                open(p, "w", encoding="utf-8").write(new)
    print(f"annotated {changed}/{files} files ({len(got)} GOT slots known)")


if __name__ == "__main__":
    main()
