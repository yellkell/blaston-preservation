"""Annotated ARM64 disassembly + xrefs for an IL2CPP libil2cpp.so (replaces Cpp2IL ISIL for Quest).

Cpp2IL mis-maps this .so (it reads code at file offset == vaddr, but the text segment is shifted
by 0x4000), so its ISIL for the Quest build disassembles the wrong bytes. This tool decodes each
method at the correct file offset with Capstone and resolves:
  ADRP+LDR  -> GOT slot -> (via R_AARCH64_RELATIVE) string literal / TypeInfo / MethodInfo / ...
  ADRP+ADD  -> direct address
  BL / B    -> method name
Outputs in <out_dir>:
  string_xrefs.tsv, call_xrefs.tsv     (same format as tools/build_xrefs.py)
  asm/<Assembly>/<Namespace.Class>.txt (annotated listings for classes whose group matches --annotate)

Usage: python arm64_disasm.py libil2cpp.so metadata.json symbols.tsv out_dir [--annotate A,B,...]
"""
import json
import os
import struct
import sys

import capstone
from capstone import arm64_const as A

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from add_got_symbols import relative_relocs  # noqa: E402

MAX_FN = 0x8000
CALLEE_SAVED = {getattr(A, f"ARM64_REG_X{i}") for i in range(19, 29)}


def load_segments(data):
    e_phoff, = struct.unpack_from("<Q", data, 0x20)
    e_phentsize, e_phnum = struct.unpack_from("<HH", data, 0x36)
    segs = []
    for i in range(e_phnum):
        p_type, _, p_offset, p_vaddr, _, p_filesz = struct.unpack_from("<IIQQQQ", data, e_phoff + i * e_phentsize)
        if p_type == 1:
            segs.append((p_vaddr, p_vaddr + p_filesz, p_offset))
    return segs


def v2o(segs, va):
    for lo, hi, off in segs:
        if lo <= va < hi:
            return off + (va - lo)
    return None


def main():
    args = sys.argv[1:]
    annotate = []
    if "--annotate" in args:
        i = args.index("--annotate")
        annotate = args[i + 1].split(",")
        del args[i: i + 2]
    so_path, meta_path, sym_path, out_dir = args
    data = open(so_path, "rb").read()
    segs = load_segments(data)
    relocs = dict(relative_relocs(so_path))

    syms = {}
    for line in open(sym_path, encoding="utf-8"):
        a, k, label = line.rstrip("\n").split("\t", 2)
        syms[int(a, 16)] = (k, label)

    am = json.load(open(meta_path, encoding="utf-8"))["addressMap"]
    methods = {}
    for e in am["methodDefinitions"]:
        methods.setdefault(int(e["virtualAddress"], 16), (e["group"], e["dotNetSignature"]))
    for e in am["constructedGenericMethods"]:
        methods.setdefault(int(e["virtualAddress"], 16), ("__generic__/" + e["name"][:80], e["signature"]))
    bounds = sorted(set(methods) | {int(a, 16) for a in am["functionAddresses"] if int(a, 16)})

    def label(addr):
        if addr in syms:
            return syms[addr]
        t = relocs.get(addr)
        if t is not None and t in syms:
            return syms[t]
        return None

    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    md.detail = True
    os.makedirs(out_dir, exist_ok=True)
    sx = open(os.path.join(out_dir, "string_xrefs.tsv"), "w", encoding="utf-8")
    cx = open(os.path.join(out_dir, "call_xrefs.tsv"), "w", encoding="utf-8")
    listings = {}

    import bisect
    for n, start in enumerate(sorted(methods)):
        group, sig = methods[start]
        if group.startswith("__generic__"):
            continue
        k = bisect.bisect_right(bounds, start)
        end = min(bounds[k] if k < len(bounds) else start + MAX_FN, start + MAX_FN)
        off = v2o(segs, start)
        if off is None:
            continue
        want = any(s in group for s in annotate)
        lines = [f"Method: {sig}  @ {start:#x}"] if want else None
        pages = {}
        seen = set()
        where = f"{group}::{sig}"
        for insn in md.disasm(data[off: off + (end - start)], start):
            note = None
            ops = insn.operands
            if insn.id == A.ARM64_INS_ADRP and len(ops) == 2:
                pages[ops[0].reg] = ops[1].imm
            elif insn.id in (A.ARM64_INS_LDR, A.ARM64_INS_ADD) and len(ops) >= 2:
                base = None
                if ops[-1].type == A.ARM64_OP_MEM and ops[-1].mem.base in pages:
                    base = pages[ops[-1].mem.base] + ops[-1].mem.disp
                elif insn.id == A.ARM64_INS_ADD and len(ops) == 3 and ops[1].type == A.ARM64_OP_REG \
                        and ops[1].reg in pages and ops[2].type == A.ARM64_OP_IMM:
                    base = pages[ops[1].reg] + ops[2].imm
                if base is not None:
                    note = label(base)
            elif insn.id in (A.ARM64_INS_BL, A.ARM64_INS_B) and ops and ops[0].type == A.ARM64_OP_IMM:
                tgt = ops[0].imm
                if tgt in methods:
                    note = ("M", f'{methods[tgt][0].split("/", 1)[-1]}::{methods[tgt][1]}')
                elif tgt in syms:
                    note = syms[tgt]
            # a register overwritten by anything other than ADRP no longer holds a page base
            if insn.id != A.ARM64_INS_ADRP and ops and ops[0].type == A.ARM64_OP_REG:
                pages.pop(ops[0].reg, None)
            if insn.id == A.ARM64_INS_BL:  # calls clobber argument/scratch registers x0-x18
                for r in list(pages):
                    if r not in CALLEE_SAVED:
                        del pages[r]
            if note:
                key = note
                if key not in seen:
                    seen.add(key)
                    if note[0] == "S":
                        sx.write(f"{note[1]}\t{where}\n")
                    elif note[0] in "MGA" and insn.id in (A.ARM64_INS_BL, A.ARM64_INS_B):
                        cx.write(f"{note[1]}\t{where}\n")
            if lines is not None:
                txt = f"  {insn.address:08x}  {insn.mnemonic:6} {insn.op_str}"
                lines.append(txt + (f"    ; {note[0]}:{note[1]}" if note else ""))
            if insn.id == A.ARM64_INS_RET and insn.address + 4 >= end:
                break
        if lines is not None:
            listings.setdefault(group, []).append("\n".join(lines))
        if n % 20000 == 0:
            print(f"  {n}/{len(methods)} methods", flush=True)

    for group, parts in listings.items():
        asm_name, _, cls = group.partition("/")
        d = os.path.join(out_dir, "asm", asm_name.replace(".dll", ""))
        os.makedirs(d, exist_ok=True)
        fn = "".join(c if c.isalnum() or c in "._-" else "_" for c in cls)[:150] + ".txt"
        with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
            f.write("\n\n".join(parts) + "\n")
    print(f"done: {len(listings)} annotated classes -> {out_dir}")


if __name__ == "__main__":
    main()
