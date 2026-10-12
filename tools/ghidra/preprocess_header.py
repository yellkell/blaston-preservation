"""Minimal C preprocessor for Il2CppInspector's il2cpp-types.h, targeting Ghidra's CParser.

Handles #if/#elif defined(...) with ||, &&, !; #ifdef/#ifndef/#else/#endif; #define NAME (flags only); #undef.
Drops #pragma lines (Ghidra's CParser doesn't need pack pragmas for these generated structs).
Usage: python preprocess_header.py in.h out.h [-DNAME ...]   (default defines: _GHIDRA_)
"""
import re
import sys

TOKEN = re.compile(r"defined\s*\(\s*(\w+)\s*\)|defined\s+(\w+)|\|\||&&|!|\(|\)|\w+")


def evaluate(expr: str, defs: set) -> bool:
    toks = []
    for m in TOKEN.finditer(expr):
        if m.group(1) or m.group(2):
            toks.append("True" if (m.group(1) or m.group(2)) in defs else "False")
        else:
            t = m.group(0)
            toks.append({"||": " or ", "&&": " and ", "!": " not "}.get(t, t if t in "()" else
                        ("True" if t in defs else "False") if not t.isdigit() else ("True" if int(t) else "False")))
    return bool(eval("".join(toks)))  # noqa: S307 - only True/False/and/or/not/() tokens


def main():
    src, dst = sys.argv[1], sys.argv[2]
    defs = {"_GHIDRA_"} | {a[2:] for a in sys.argv[3:] if a.startswith("-D")}
    stack = []  # (parent_active, this_branch_taken, currently_active)
    active = True
    out = []
    for line in open(src, encoding="utf-8", errors="replace"):
        s = line.strip()
        if s.startswith("#"):
            d = s[1:].strip()
            word = d.split(None, 1)[0] if d else ""
            rest = d[len(word):].strip()
            if word in ("if", "ifdef", "ifndef"):
                cond = (evaluate(rest, defs) if word == "if" else
                        (rest in defs) if word == "ifdef" else (rest not in defs))
                stack.append((active, active and cond))
                active = active and cond
            elif word == "elif":
                parent, taken = stack[-1]
                cond = parent and not taken and evaluate(rest, defs)
                stack[-1] = (parent, taken or cond)
                active = cond
            elif word == "else":
                parent, taken = stack[-1]
                active = parent and not taken
                stack[-1] = (parent, True)
            elif word == "endif":
                active = stack.pop()[0]
            elif active and word == "define":
                defs.add(rest.split()[0])
            elif active and word == "undef":
                defs.discard(rest.split()[0])
            continue  # never emit directives
        if active:
            out.append(line)
    open(dst, "w", encoding="utf-8").write("".join(out))
    print(f"{src} -> {dst}: {len(out)} lines, defines={sorted(defs)}")


if __name__ == "__main__":
    main()
