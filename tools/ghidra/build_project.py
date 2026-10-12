"""Headless Ghidra pipeline for Blaston's IL2CPP binary (PyGhidra 3.x, Ghidra 12).

Stages (each is skipped when already done, so the script can be re-run after a failure):
  1. import      libil2cpp.so / GameAssembly.dll into a Ghidra project (no analysis yet), image base 0
  2. types       parse the preprocessed Il2CppInspector C header into the program's data types
  3. symbols     run Il2CppInspector's ghidra_il2cpp.py (method names/signatures, string literals, metadata)
  4. analyze     Ghidra auto-analysis (Decompiler Parameter ID disabled: huge cost, little gain with typed sigs)

Usage (from the repo root, with the PyGhidra venv):
  external/pyghidra-venv/Scripts/python -I tools/ghidra/build_project.py <binary> <inspector_dir> <header.h> <project_dir> <language_id>
e.g. dump-quest/input/libil2cpp.so dump-quest/inspector dump-quest/ghidra/il2cpp-types.ghidra.h dump-quest/ghidra AARCH64:LE:64:v8A
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GHIDRA = ROOT / "external/ghidra/ghidra_12.1.4_PUBLIC"
JDK = next((ROOT / "external/jdk21").glob("jdk-*"))
os.environ["JAVA_HOME"] = str(JDK)
os.environ["GHIDRA_INSTALL_DIR"] = str(GHIDRA)

import pyghidra  # noqa: E402


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def main():
    binary, inspector_dir, header, project_dir, lang = (Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(),
                                                        Path(sys.argv[3]).resolve(), Path(sys.argv[4]).resolve(),
                                                        sys.argv[5])
    project_dir.mkdir(parents=True, exist_ok=True)
    launcher = pyghidra.HeadlessPyGhidraLauncher(install_dir=GHIDRA)
    launcher.add_vmargs("-Xmx24g", "-XX:+UseG1GC")
    launcher.start()

    from java.io import FileInputStream  # noqa
    from ghidra.app.util.cparser.C import CParser  # noqa
    from ghidra.program.model.data import CategoryPath  # noqa

    name = "blaston"
    prog_path = "/" + binary.name
    project = pyghidra.open_project(project_dir, name, create=True)
    if project.getProjectData().getFile(prog_path) is None:
        log(f"[1/4] importing {binary.name} as {lang}")
        project.close()
        with pyghidra.open_program(binary, project_location=project_dir, project_name=name, analyze=False,
                                   language=lang, nested_project_location=False) as api:
            prog = api.getCurrentProgram()
            if prog.getExecutableFormat().endswith("(ELF)"):
                with pyghidra.transaction(prog, "image base 0"):
                    prog.setImageBase(api.toAddr(0), True)
        project = pyghidra.open_project(project_dir, name)
    else:
        log("[1/4] already imported")

    with pyghidra.program_context(project, prog_path) as prog:
        monitor = pyghidra.task_monitor()
        opts = prog.getOptions("Program Information")
        dtm = prog.getDataTypeManager()

        if not opts.getBoolean("blaston.types", False):
            log(f"[2/4] parsing {header.name} ({header.stat().st_size // 1_000_000} MB)")
            with pyghidra.transaction(prog, "il2cpp types"):
                parser = CParser(dtm, True, None)
                stream = FileInputStream(str(header))
                try:
                    parser.parse(stream)
                finally:
                    stream.close()
                opts.setBoolean("blaston.types", True)
            prog.save("il2cpp types", monitor)
            log(f"      types now: {dtm.getDataTypeCount(True)}")
        else:
            log("[2/4] types already parsed")

        if not opts.getBoolean("blaston.symbols", False):
            script = inspector_dir / "ghidra_il2cpp.py"
            log(f"[3/4] running {script.name} (reads {inspector_dir / 'metadata.json'})")
            pyghidra.ghidra_script(script, project, prog, echo_stdout=True, echo_stderr=True)
            with pyghidra.transaction(prog, "mark symbols"):
                opts.setBoolean("blaston.symbols", True)
            prog.save("il2cpp symbols", monitor)
        else:
            log("[3/4] symbols already applied")

        if not opts.getBoolean("blaston.analyzed", False):
            log("[4/4] auto-analysis (long)")
            aopts = prog.getOptions("Analyzers")
            with pyghidra.transaction(prog, "analysis options"):
                for k in ("Decompiler Parameter ID", "Aggressive Instruction Finder"):
                    if aopts.contains(k):
                        aopts.setBoolean(k, False)
            pyghidra.analyze(prog, monitor)
            with pyghidra.transaction(prog, "mark analyzed"):
                opts.setBoolean("blaston.analyzed", True)
            prog.save("auto-analysis", monitor)
        else:
            log("[4/4] already analyzed")
        log(f"functions: {prog.getFunctionManager().getFunctionCount()}")
    project.close()
    log("done")


if __name__ == "__main__":
    main()
