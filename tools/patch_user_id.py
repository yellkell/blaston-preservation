"""Pin the Meta user ID Blaston (Quest build) sees, so the Frame build always logs into the same PlayFab account.

Patches Oculus.Platform.CAPI.ovr_User_GetID(IntPtr) in libil2cpp.so to `return <ID>;`
(movz/movk x0 + ret). Every Oculus.Platform.Models.User then reports this ID; Blaston uses the
logged-in user's ID as its PlayFab CustomID (OculusFacade.SetOculusUserData).

Usage: python patch_user_id.py <in.apk> <out.apk> <user_id> [--file-offset 0x4410FDC]
The default offset is for Quest build 2.3.3.302372 (verified prologue below); re-derive it for other builds
from dump-quest/symbols.tsv (vaddr 0x4414FDC) via the ELF segment mapping.
"""
import struct
import sys
import zipfile

LIB = "lib/arm64-v8a/libil2cpp.so"
EXPECTED_PROLOGUE = bytes.fromhex("ff4301d1fe1b00f9f44f04a9b4a50090f30300aa")  # sub sp; str x30; stp; adrp; mov


def encode(uid: int) -> bytes:
    words = []
    for i in range(4):
        imm = (uid >> (16 * i)) & 0xFFFF
        base = 0xD2800000 if i == 0 else 0xF2800000  # MOVZ / MOVK  (64-bit)
        words.append(base | (i << 21) | (imm << 5) | 0)  # Rd = x0
    words.append(0xD65F03C0)  # RET
    return struct.pack("<5I", *words)


def main():
    src, dst, uid = sys.argv[1], sys.argv[2], int(sys.argv[3])
    off = int(sys.argv[sys.argv.index("--file-offset") + 1], 16) if "--file-offset" in sys.argv else 0x4410FDC
    zin = zipfile.ZipFile(src)
    lib = bytearray(zin.read(LIB))
    if lib[off:off + 20] != EXPECTED_PROLOGUE:
        sys.exit(f"unexpected bytes at {off:#x}: {lib[off:off+20].hex()} (wrong build/offset?)")
    lib[off:off + 20] = encode(uid)
    with zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            if info.filename.startswith("META-INF/"):
                continue  # old signature is invalid now; the APK gets re-signed downstream
            data = bytes(lib) if info.filename == LIB else zin.read(info.filename)
            zout.writestr(info, data, compress_type=info.compress_type)
    print(f"patched ovr_User_GetID -> {uid} at file offset {off:#x}; wrote {dst}")


if __name__ == "__main__":
    main()
