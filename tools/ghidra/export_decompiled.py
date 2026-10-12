"""Export Ghidra decompilation (C pseudocode) for every method in selected assemblies, one file per class.

Run after build_project.py has finished. Output layout mirrors the C# stubs:
  <out_dir>/<Assembly>/<Namespace...>/<Class>.c

Usage:
  external/pyghidra-venv/Scripts/python -I tools/ghidra/export_decompiled.py <project_dir> <program_name> <out_dir> \
      [--assemblies Assembly-CSharp.dll,Authentication.dll,ResolutionGames.] [--threads 24] [--timeout 60]
Assembly filters are prefixes of the top-level namespace; "*" exports everything.
"""
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GHIDRA = ROOT / "external/ghidra/ghidra_12.1.4_PUBLIC"
os.environ["JAVA_HOME"] = str(next((ROOT / "external/jdk21").glob("jdk-*")))
os.environ["GHIDRA_INSTALL_DIR"] = str(GHIDRA)

import pyghidra  # noqa: E402

DEFAULT_ASSEMBLIES = "Assembly-CSharp.dll,Assembly-CSharp-firstpass.dll,Authentication.dll,ResolutionGames."


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def safe(part: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in part)[:120]


def main():
    project_dir, prog_name, out_dir = Path(sys.argv[1]).resolve(), sys.argv[2], Path(sys.argv[3]).resolve()
    prefixes = [p for p in arg("--assemblies", DEFAULT_ASSEMBLIES).split(",") if p]
    threads, timeout = int(arg("--threads", "24")), int(arg("--timeout", "60"))

    launcher = pyghidra.HeadlessPyGhidraLauncher(install_dir=GHIDRA)
    launcher.add_vmargs("-Xmx24g", "-XX:+UseG1GC")
    launcher.start()
    from ghidra.app.decompiler import DecompInterface, DecompileOptions  # noqa
    from ghidra.util.task import ConsoleTaskMonitor  # noqa

    project = pyghidra.open_project(project_dir, "blaston")
    with pyghidra.program_context(project, "/" + prog_name) as prog:
        # group functions by class namespace path
        by_class = defaultdict(list)
        for f in prog.getFunctionManager().getFunctions(True):
            ns = f.getParentNamespace()
            parts = []
            while ns is not None and not ns.isGlobal():
                parts.append(ns.getName())
                ns = ns.getParentNamespace()
            parts.reverse()
            if not parts or not ("*" in prefixes or any(parts[0].startswith(p) for p in prefixes)):
                continue
            by_class[tuple(parts)].append(f)
        total = sum(len(v) for v in by_class.values())
        print(time.strftime("%H:%M:%S"), f"{len(by_class)} classes, {total} functions to decompile", flush=True)

        opts = DecompileOptions()
        opts.grabFromProgram(prog)
        pool_ifaces = []

        def iface():
            d = DecompInterface()
            d.setOptions(opts)
            d.toggleCCode(True)
            d.toggleSyntaxTree(False)
            d.setSimplificationStyle("decompile")
            d.openProgram(prog)
            return d

        import threading
        local = threading.local()
        done = [0]
        lock = threading.Lock()

        failures = []

        def decompile_class(item):
            try:
                _decompile_class(item)
            except Exception as e:  # noqa: BLE001 - one bad class must not stop the export
                failures.append(f"{'/'.join(item[0])}: {e}")

        def _decompile_class(item):
            parts, funcs = item
            if not hasattr(local, "d"):
                local.d = iface()
                pool_ifaces.append(local.d)
            chunks = [f"// {'/'.join(parts)}\n// Decompiled with Ghidra from Blaston {prog_name} (Il2CppInspector symbols)\n"]
            for f in sorted(funcs, key=lambda x: x.getEntryPoint().getOffset()):
                res = local.d.decompileFunction(f, timeout, ConsoleTaskMonitor())
                code = res.getDecompiledFunction().getC() if res and res.decompileCompleted() else \
                    f"/* decompilation failed: {res.getErrorMessage() if res else 'no result'} */\n"
                chunks.append(f"\n// {f.getName()} @ {f.getEntryPoint()}\n{code}")
            # generic instantiations put '/' inside names -> keep assembly + 3 namespace levels, flatten the rest
            dirs = [safe(p) for p in parts[:-1]]
            if len(dirs) > 4:
                dirs = dirs[:4]
            fname = safe("_".join(parts[len(dirs):]) if len(parts) - len(dirs) > 1 else parts[-1])[:150] + ".c"
            path = out_dir.joinpath(*dirs, fname)
            target = Path("\\\\?\\" + str(path)) if os.name == "nt" else path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("".join(chunks), encoding="utf-8")
            with lock:
                done[0] += len(funcs)
                if done[0] % 2000 < len(funcs):
                    print(time.strftime("%H:%M:%S"), f"{done[0]}/{total}", flush=True)

        with ThreadPoolExecutor(max_workers=threads) as ex:
            list(ex.map(decompile_class, sorted(by_class.items(), key=lambda kv: -len(kv[1]))))
        for d in pool_ifaces:
            d.dispose()
        if failures:
            (out_dir / "_export_failures.txt").write_text("\n".join(failures), encoding="utf-8")
            print(f"{len(failures)} classes failed, see _export_failures.txt", flush=True)
    project.close()
    print(time.strftime("%H:%M:%S"), f"done -> {out_dir}", flush=True)


if __name__ == "__main__":
    main()
