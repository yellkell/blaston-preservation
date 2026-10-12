"""ARM64 .so support: label GOT slots with the symbol they point to.

Code in libil2cpp.so reaches metadata usages (string literals, TypeInfo, MethodInfo...) via
`ADRP/LDR` from a GOT slot. The slot's value is set at load time by an R_AARCH64_RELATIVE
relocation (slot = base + addend). We read those relocations and, for every slot whose addend is
a known symbol, append `slot  kind  label` to the symbol table.

Usage: python add_got_symbols.py libil2cpp.so symbols.tsv   (rewrites symbols.tsv in place)
"""
import struct
import sys

R_AARCH64_RELATIVE = 1027
SHT_RELA = 4


def relative_relocs(path):
    data = open(path, "rb").read()
    assert data[:4] == b"\x7fELF" and data[4] == 2, "need ELF64"
    e_shoff, = struct.unpack_from("<Q", data, 0x28)
    e_shentsize, e_shnum = struct.unpack_from("<HH", data, 0x3A)
    for i in range(e_shnum):
        sh = e_shoff + i * e_shentsize
        sh_type, = struct.unpack_from("<I", data, sh + 4)
        if sh_type != SHT_RELA:
            continue
        sh_offset, sh_size, _, _, _, sh_entsize = struct.unpack_from("<QQIIQQ", data, sh + 0x18)
        for off in range(sh_offset, sh_offset + sh_size, sh_entsize or 24):
            r_offset, r_info, r_addend = struct.unpack_from("<QQq", data, off)
            if r_info & 0xFFFFFFFF == R_AARCH64_RELATIVE:
                yield r_offset, r_addend


def inplace_pointers(path):
    """Yield (vaddr, value) for every 8-byte slot in writable PT_LOAD segments.

    With RELR packed relocations (modern NDK), the relocation addend is stored in place,
    so the file content of each GOT / data slot already holds the target address.
    """
    data = open(path, "rb").read()
    e_phoff, = struct.unpack_from("<Q", data, 0x20)
    e_phentsize, e_phnum = struct.unpack_from("<HH", data, 0x36)
    for i in range(e_phnum):
        ph = e_phoff + i * e_phentsize
        p_type, p_flags, p_offset, p_vaddr, _, p_filesz = struct.unpack_from("<IIQQQQ", data, ph)
        if p_type != 1 or not (p_flags & 2):  # PT_LOAD with PF_W
            continue
        start = p_offset + (-p_vaddr % 8)
        for off in range(start, p_offset + p_filesz - 7, 8):
            yield p_vaddr + (off - p_offset), struct.unpack_from("<Q", data, off)[0]


def main():
    so, sym_path = sys.argv[1], sys.argv[2]
    syms = {}
    for line in open(sym_path, encoding="utf-8"):
        a, k, label = line.rstrip("\n").split("\t", 2)
        syms[int(a, 16)] = (k, label)
    added = 0
    for slot, target in list(relative_relocs(so)) + list(inplace_pointers(so)):
        if target in syms and slot not in syms:
            syms[slot] = syms[target]
            added += 1
    with open(sym_path, "w", encoding="utf-8") as f:
        for a in sorted(syms):
            f.write(f"{a:X}\t{syms[a][0]}\t{syms[a][1]}\n")
    print(f"added {added} GOT-slot symbols -> {sym_path}")


if __name__ == "__main__":
    main()
