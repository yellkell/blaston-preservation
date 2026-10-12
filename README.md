# reverseblaston workspace

Goal: keep Blaston playable on self-hosted / self-owned backends if Resolution Games shuts down its servers. See [FINDINGS.md](FINDINGS.md) for what we know.

Analysed build: Steam app 1427890, buildid 19793134, Unity 6000.2.0f1, IL2CPP metadata v31, `build-guid=da2b7d9f346d47f6bfe096d08251dd25`.
**If Steam updates the game, every address below changes.** Regenerate everything (see bottom).

## Layout

| Path | What | Use it for |
|---|---|---|
| `dump/cs/DiffableCs/<Assembly>/<Namespace>/<Class>.cs` | Cpp2IL C# stubs: classes, fields (with offsets), method signatures | Reading request/response DTOs and service APIs. Start in `ResolutionGames.Services/Fidelity/MercuryServices`, `Authentication/Fidelity/Authentication`, `Assembly-CSharp/RGCommon/{PlayFab,ServerClient,Login}`, `Assembly-CSharp/RG/Ignis` |
| `dump/dummydll/*.dll` | Cpp2IL stub DLLs | Open in ILSpy / dnSpy to browse the structure |
| `dump/inspector/types.cs` | Il2CppInspector single-file C# with method RVAs | grep for a method → address |
| `dump/inspector/dll/` | Il2CppInspector shim DLLs (with address attributes) | ILSpy/dnSpy, BepInEx/Il2CppInterop modding later |
| `dump/inspector/metadata.json` | Full address map (methods, string literals, TypeInfo, MethodInfo) | Source for `dump/symbols.tsv` |
| `dump/inspector/ghidra_il2cpp.py` + `dump/inspector/cpp/` | Ghidra import script + C++ type headers | Load `GameAssembly.dll` into Ghidra, then run the script to name every function/string/type |
| `dump/isil/IsilDump/...txt` | Cpp2IL per-method x64 disassembly | Raw method bodies |
| `dump/isil/IsilDump/...annotated.txt` | Same, with every address resolved to a method name / string literal / type | **Reading backend logic without a disassembler** (pre-generated for all RG/Fidelity/Ignis/Bowser/PlayFab code) |
| `dump/symbols.tsv` | `address  kind  label` (195k entries) | Look up any address |
| `dump/xrefs/string_xrefs.tsv` | `"literal"  file::method` | "Which code uses this URL / key / string?" |
| `dump/xrefs/call_xrefs.tsv` | `callee  file::method` | "Who calls X?" |
| `dump/xrefs/rg_endpoints.tsv` | Every URL/REST path literal used by RG/PlayFab code + the class using it | The server API surface we must emulate |
| `dump/literals.txt`, `dump/names.txt` | Raw metadata string literals / identifiers | Quick greps |
| `dump/settings_assets.txt` | Strings from serialized settings assets (Photon, Mercury, auth…) | Config values not in code |

Caveat: the compiler folds identical functions (COMDAT folding), so a call can be labelled with an unrelated method that has the same body (e.g. a trivial getter showing up as `PanelSettings::get_themeStyleSheet`). Trust string literals and MethodInfo labels over these.

## Tools

- `external/cpp2il/` — Cpp2IL 2022.1.0-pre-release.21 (SamboyCoding/Cpp2IL)
- `external/il2cppinspector/legacy/` — Il2CppInspectorRedux 2026.2 Legacy CLI (LukeFZ/Il2CppInspectorRedux); needs `DOTNET_ROOT=external/dotnet10`
- `external/dotnet10/` — project-local .NET 10 runtime (not installed system-wide)
- `.venv/` — Python venv with UnityPy
- `tools/*.py` — our scripts

## Regenerate everything (after a game update)

```bash
G="C:/Program Files (x86)/Steam/steamapps/common/Blaston"
M="$G/Blaston_Data/il2cpp_data/Metadata/global-metadata.dat"
python -I tools/dump_literals.py "$M" dump/literals.txt
python -I tools/dump_names.py "$M" dump/names.txt
.venv/Scripts/python -I tools/dump_settings_assets.py "$G/Blaston_Data/data.unity3d" > dump/settings_assets.txt
C=external/cpp2il/Cpp2IL-2022.1.0-pre-release.21-Windows.exe
$C --game-path "$G" --exe-name Blaston --output-as dummydll   --output-to dump/dummydll
$C --game-path "$G" --exe-name Blaston --output-as diffable-cs --output-to dump/cs
$C --game-path "$G" --exe-name Blaston --output-as isil        --output-to dump/isil
DOTNET_ROOT="$(cygpath -w external/dotnet10)" external/il2cppinspector/legacy/Il2CppInspectorRedux.Legacy.CLI-win-x64/Il2CppInspector.exe \
  -i "$G/GameAssembly.dll" -m "$M" -t Ghidra -p dump/inspector/ghidra_il2cpp.py -o dump/inspector/metadata.json \
  -h dump/inspector/cpp -c dump/inspector/types.cs -l single -e none -d dump/inspector/dll
python -I tools/build_symbols.py dump/inspector/metadata.json dump/symbols.tsv
python -I tools/build_xrefs.py dump/symbols.tsv dump/isil/IsilDump dump/xrefs \
  --annotate "ResolutionGames.,Authentication/,RGCommon/,Assembly-CSharp/RG/,Assembly-CSharp/Ignis/,Assembly-CSharp/Bowser/,Assembly-CSharp/IgnisBowser/,PlayFab/PlayFab"
```

Annotate any other ISIL file ad hoc: `python -I tools/annotate_isil.py dump/symbols.tsv <file.txt> --stdout`

## Quest build (`dump-quest/`)

Same layout as `dump/`, generated from `backup/quest/2.3.3.302372/base.apk` (`dump-quest/input/` holds the extracted `libil2cpp.so` + `global-metadata.dat`):
`cs/` (Cpp2IL C# stubs), `dummydll/`, `inspector/` (types.cs, metadata.json, Ghidra script, shim DLLs), `symbols.tsv`, and
`xrefs/` = `string_xrefs.tsv`, `call_xrefs.tsv` + **`xrefs/asm/<Assembly>/<Class>.txt`**: correct annotated ARM64 listings for all RG/Fidelity/Ignis/Bowser/PlayFab/Oculus classes.
**Don't use Cpp2IL ISIL for Quest** (mis-mapped; see FINDINGS.md).

Regenerate (after pulling a new APK with `adb shell pm path com.resolutiongames.ignis` + `adb pull`):
```bash
# extract lib/arm64-v8a/libil2cpp.so and assets/bin/Data/Managed/Metadata/global-metadata.dat into dump-quest/input/, then:
I=dump-quest/input; Q=dump-quest; C=external/cpp2il/Cpp2IL-2022.1.0-pre-release.21-Windows.exe
$C --force-binary-path $I/libil2cpp.so --force-metadata-path $I/global-metadata.dat --force-unity-version 6000.2.0f1 --output-as diffable-cs --output-to $Q/cs
DOTNET_ROOT="$(cygpath -w external/dotnet10)" external/il2cppinspector/legacy/Il2CppInspectorRedux.Legacy.CLI-win-x64/Il2CppInspector.exe   -i $I/libil2cpp.so -m $I/global-metadata.dat -t Ghidra -p $Q/inspector/ghidra_il2cpp.py -o $Q/inspector/metadata.json   -h $Q/inspector/cpp -c $Q/inspector/types.cs -l single -e none -d $Q/inspector/dll
python -I tools/build_symbols.py $Q/inspector/metadata.json $Q/symbols.tsv
.venv/Scripts/python -I tools/arm64_disasm.py $I/libil2cpp.so $Q/inspector/metadata.json $Q/symbols.tsv $Q/xrefs   --annotate "ResolutionGames.,Authentication.dll,RGCommon,Assembly-CSharp.dll/RG.,Assembly-CSharp.dll/Ignis,Assembly-CSharp.dll/Bowser,PlayFab.dll/PlayFab,Oculus"
```

## Live traffic capture (do this while official servers are up)

`backup/steam-build-19793134/` holds a full copy of the analysed Steam build (Blaston + BlastonSpectator + app manifests).

1. Trust mitmproxy's certificate (current user only), once:
   `certutil -user -addstore Root "$env:USERPROFILE\.mitmproxy\mitmproxy-ca-cert.cer"`
   To undo later: `certutil -user -delstore Root mitmproxy`
2. Start capture (UAC prompt; Ctrl+C to stop):
   `powershell -ExecutionPolicy Bypass -File tools\capture.ps1 -Name <session-name>`
3. Launch Blaston from Steam and play. Output lands in `capture/<session-name>/`:
   `flows.jsonl` (everything), `by_host/*.jsonl`, `endpoints.txt` (summary), `raw.flows` (open with `.venv/Scripts/mitmweb -r`).

**Captures contain live auth tokens/session tickets. Do not share raw captures.**

## Full decompilation + assets (Quest build, 2026-10-11)

| Path | What |
|---|---|
| `dump-quest/decompiled/<Assembly>/<Namespace>/<Class>.c` | **Ghidra C pseudocode for every method** of Blaston's own code (3,590 classes / 18,625 methods: Assembly-CSharp*, Authentication, ResolutionGames.*). Real names for classes, methods, fields and calls; string literals / `typeof(...)` / MethodInfo shown as `/*...*/` comments. Only 2 functions failed to decompile. |
| `dump-quest/ghidra/blaston.gpr` | The analysed Ghidra project (327k functions, 348k types). Open it with `external/ghidra/ghidra_12.1.4_PUBLIC/ghidraRun.bat` (set `JAVA_HOME` to `external/jdk21/jdk-21.0.12.1+1`) to browse interactively. |
| `dump-quest/assetripper/BlastonUnityProject/` | **Full Unity project export** (AssetRipper 2.0): 17 scenes (all arenas + Arcade), 874 prefabs, meshes, textures, materials, shaders, animations, audio, original `Assets/RG/...` layout. Open in Unity 6000.2; the scripts are stubs. One ASTC-HDR texture couldn't be converted. |

Caveat: the Ghidra project's ELF relocations were applied at Ghidra's default image base (0x100000) before re-basing to 0. Code addresses are correct, but pointer *values* in data are +0x100000, so the decompiler prints `DAT_`/`PTR_DAT_` labels instead of symbol names. `tools/ghidra/annotate_decompiled.py` compensates in the exported C. For a perfectly labelled project, re-import with `-loader-imagebase 0` and rerun `tools/ghidra/build_project.py` (~2.5 h).

Regenerate: `external/pyghidra-venv/Scripts/python -I tools/ghidra/build_project.py dump-quest/input/libil2cpp.so dump-quest/inspector dump-quest/ghidra/il2cpp-types.ghidra.h dump-quest/ghidra AARCH64:LE:64:v8A`, then `tools/ghidra/export_decompiled.py dump-quest/ghidra libil2cpp.so dump-quest/decompiled`, then `python -I tools/ghidra/annotate_decompiled.py dump-quest/input/libil2cpp.so dump-quest/symbols.tsv dump-quest/decompiled`. The header comes from `tools/ghidra/preprocess_header.py dump-quest/inspector/cpp/appdata/il2cpp-types.h`.
