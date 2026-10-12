"""Find MonoBehaviour settings assets (PlayFab/Photon/Mercury) in Blaston's data and dump their raw strings.

IL2CPP player builds strip type trees, so we can't decode fields by name; instead we
read each MonoBehaviour's raw bytes and pull out the length-prefixed strings Unity serializes.
"""
import re
import struct
import sys

import UnityPy

INTERESTING = re.compile(r"(?i)playfab|photon|mercury|settings|config|server|backend|title")


def unity_strings(raw: bytes):
    """Yield Unity-serialized strings: int32 length + UTF-8 bytes, 4-byte aligned."""
    i = 0
    while i + 4 <= len(raw):
        (n,) = struct.unpack_from("<i", raw, i)
        if 2 <= n <= 512 and i + 4 + n <= len(raw):
            s = raw[i + 4: i + 4 + n]
            try:
                t = s.decode("utf-8")
                if t.isprintable():
                    yield t
                    i += 4 + ((n + 3) & ~3)
                    continue
            except UnicodeDecodeError:
                pass
        i += 4


def main():
    env = UnityPy.load(*sys.argv[1:])
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            raw = obj.get_raw_data()
            mb = obj.read(check_read=False)
            script = mb.m_Script.read() if mb.m_Script else None
            cls = f"{script.m_Namespace}.{script.m_ClassName}" if script else "?"
            name = getattr(mb, "m_Name", "")
        except Exception as e:  # noqa: BLE001
            continue
        if not (INTERESTING.search(cls) or INTERESTING.search(name)):
            continue
        strs = [s for s in unity_strings(raw[28:]) if s != name]
        print(f"## {cls}  name={name!r}  size={len(raw)}")
        for s in strs[:60]:
            print("   ", s)


if __name__ == "__main__":
    main()
