"""Dump string literals from an IL2CPP global-metadata.dat (v24-v31)."""
import struct
import sys

path, out = sys.argv[1], sys.argv[2]
data = open(path, "rb").read()
sanity, version = struct.unpack_from("<Ii", data, 0)
assert sanity == 0xFAB11BAF, hex(sanity)

# Header: after sanity+version come (offset, size) int32 pairs.
# Pair 0 = stringLiteral table, pair 1 = stringLiteralData.
lit_off, lit_size, litdata_off, litdata_size = struct.unpack_from("<iiii", data, 8)

# Table entries are (uint32 length, uint32 dataIndex) — still true for Blaston's v31 build.
literals = []
n = lit_size // 8
for i in range(n):
    length, index = struct.unpack_from("<II", data, lit_off + i * 8)
    literals.append(data[litdata_off + index: litdata_off + index + length])

with open(out, "w", encoding="utf-8") as f:
    for i, b in enumerate(literals):
        s = b.decode("utf-8", "replace").replace("\r", "\\r").replace("\n", "\\n")
        f.write(f"{i}\t{s}\n")
print(f"version {version}: {len(literals)} literals -> {out}")
