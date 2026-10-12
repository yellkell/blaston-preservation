"""Dump the identifier string table (type/method/field names) from global-metadata.dat."""
import struct
import sys

path, out = sys.argv[1], sys.argv[2]
data = open(path, "rb").read()
# Pair 2 = string (identifier) table: null-terminated UTF-8 names
str_off, str_size = struct.unpack_from("<ii", data, 8 + 16)
blob = data[str_off: str_off + str_size]
names = [s.decode("utf-8", "replace") for s in blob.split(b"\0") if s]
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(names))
print(f"{len(names)} identifiers -> {out}")
