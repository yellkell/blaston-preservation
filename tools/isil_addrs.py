"""Extract referenced addresses from one line of a Cpp2IL ISIL dump (x64 or ARM64).

x64:   absolute addresses appear directly, e.g. `lea rcx,[1837DD840h]`, `call 00000001817F6D40h`.
ARM64: addresses are built from `ADRP Xn, <page>` + `LDR/ADD Xm, [Xn + <off>]`, or appear directly
       as `BL 0x35F1E24` and in the ISIL section as `[0x2BF5EC8]`.
"""
import re

X64_ADDR = re.compile(r"\b0*([0-9A-Fa-f]{9,16})h?\b")
ARM_HEX = re.compile(r"0x([0-9A-Fa-f]{5,16})\b")
# Cpp2IL prints ADRP's operand relative to the instruction's own 4K page: page = (pc & ~0xFFF) + imm
ARM_ADRP = re.compile(r"^\s*0x([0-9A-Fa-f]+) ADRP (X\d+), 0x([0-9A-Fa-f]+)")
ARM_INSN_ADDR = re.compile(r"^\s*0x[0-9A-Fa-f]+ ")
ARM_PAGEOFF = re.compile(r"\b(?:LDR|ADD|STR) X\d+, \[?(X\d+) \+ 0x([0-9A-Fa-f]+)\]?")


class AddrExtractor:
    """Stateful per method: remembers ADRP page registers to resolve the following LDR/ADD."""

    def __init__(self):
        self.pages = {}

    def reset(self):
        self.pages.clear()

    def __call__(self, line: str):
        out = [int(m.group(1), 16) for m in X64_ADDR.finditer(line)]
        if "ADRP" in line or " + 0x" in line or "0x" in line:
            m = ARM_ADRP.search(line)
            if m:
                pc = int(m.group(1), 16)
                self.pages[m.group(2)] = (pc & ~0xFFF) + int(m.group(3), 16)
                return out
            m = ARM_PAGEOFF.search(line)
            if m and m.group(1) in self.pages:
                out.append(self.pages[m.group(1)] + int(m.group(2), 16))
            # don't treat the instruction's own address (line prefix) as a reference
            out += [int(h, 16) for h in ARM_HEX.findall(ARM_INSN_ADDR.sub("", line))]
        return out
