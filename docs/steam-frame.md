# Running Blaston natively on Valve Steam Frame

Research date: 2026-10-10. Scope: running Blaston **on the headset itself** (standalone), not streamed from a PC.

Legend: **[C]** = confirmed by a cited source. **[R]** = reported by a community project or tester; plausible but not independently verified. **[S]** = my speculation or inference. **[?]** = unknown or unreleased as of today.

---

## TL;DR

- Steam Frame has shipped. It runs SteamOS (Arch-based, ARM64) on a Snapdragon 8 Gen 3 with 16 GB of RAM. It has three compatibility layers: **Proton** (Windows), **FEX** (x86 to ARM64) and **Lepton** (Android, a Waydroid-derived container running Android 11). The on-device XR runtime is **SteamVR**, which exposes OpenXR to both Linux and Android apps. **[C]**
- Valve's own docs only cover Android builds made **for** the Frame: Unity OpenXR plugin, Meta XR features disabled. Valve says nothing about running stock Quest APKs. **[C]**
- In practice, community tooling built on **OVRPort** patches Quest APKs. The tools are FramePort, Frame Control and FrameLoad. OVRPort swaps in its own OpenXR dispatcher and Meta-platform loader, which strips entitlement checks. FramePort lists about 80 Quest titles working, many of them Unity/OVRPlugin/GLES games like Blaston. **[R]**
- Blaston's Quest APK suits that path well: arm64-only, OVRPlugin on OpenXR (Meta `libopenxr_loader.so`, **no `libvrapi.so`**), and minSdk 32, which is at or below the Quest 12L level and so fine. Blaston itself has not been reported tested. **[S]**
- The Windows build via Proton+FEX locally is the zero-modification option, but it is the riskier one for VR. Proton VR startup on the Frame needed a community OpenXR-version workaround as of late September. You also pay x86 translation plus DX11-to-Vulkan overhead on a ~10 W SoC. **[R]/[S]**
- **Recommendation:** try the Steam/Windows build once on the headset because it costs nothing. Invest in the **Quest APK + OVRPort/FramePort + Lepton** path, because it is the better long-term route for the preservation goal.

---

## 1. Hardware, OS, XR runtime, x86 support

### Confirmed
- **SoC / RAM / OS:** Qualcomm Snapdragon 8 Gen 3 (about 10 W sustained), 16 GB LPDDR5X, and SteamOS (Arch-based) on ARM64. Panels are 2160×2160 per eye at 72–144 Hz (144 is experimental).
  - https://www.uploadvr.com/valve-steam-frame-official-announcement-features-details
  - https://partner.steamgames.com/doc/steamhardware/steamframe/compatibility
  - https://hwbusters.com/news/valve-ships-lepton-and-fex-on-steam-steam-frames-software-stack-goes-public/
- **Release:** $1,059 (256 GB) and $1,299 (1 TB). Reservations opened around 2026-09-14 to 09-17, and the first purchase emails and shipments started around 2026-09-18. Some sources dated before mid-September still say there was no price or date. Those are simply older.
  - https://steamdeckhq.com/news/the-steam-frame-officially-launches-available-from-1059/
  - https://www.dexerto.com/gaming/valve-reveals-steam-frame-price-and-release-date-starting-at-1059-3408909/
  - https://9to5google.com/2026/09/18/valves-open-source-lepton-brings-android-games-to-the-1059-steam-frame/
- **Valve's stated philosophy:** "for most developers" the path is Windows x86 via Proton + FEX. VR developers who already have an Android ARM64 mobile build can ship that instead. Proton uses DXVK, so D3D maps to Vulkan, Frame's native API. FEX translates 32- and 64-bit x86 to ARM64 and forwards GL/Vulkan calls to host libraries.
  - https://partner.steamgames.com/doc/steamhardware/steamframe/compatibility
- **Valve's performance claims:** UploadVR quotes Valve calling the FEX cost "shockingly small". VR.org reports Valve engineers putting it at about 10–20%. Heavy titles (e.g. Half-Life: Alyx) are meant to be streamed instead.
  - https://www.uploadvr.com/valve-steam-frame-official-announcement-features-details
  - https://vr.org/articles/valve-lepton-fex-steam-frame-translation-layers-2026
- **Steam Frame badge program** ("Steam Frame Verified" / "Great on Frame"):
  - Tiers are Verified, Playable, Unsupported and Unknown.
  - VR titles must reach **≥72 fps at 1728×1728 per eye**. Below 1440×1440 a title is Unsupported.
  - Controller models must show Frame controllers.
  - The review covers only local play, and a badge does not gate availability.
  - Windows-only games are reviewed under Proton.
  - https://partner.steamgames.com/doc/steamhardware/steamframe/compat
  - Valve also publishes a store page: https://store.steampowered.com/greatonframe
  - GamingOnLinux reports 200+ Verified games as of October 2026: https://www.gamingonlinux.com/2026/10/theres-now-over-200-steam-frame-verified-games/
- **How a game declares local ARM support:** there are three routes.
  - (a) Ship an **Android depot** (APK + optional OBB, OS = Android, the APK as the launch executable). https://partner.steamgames.com/doc/steamhardware/steamframe/apk_upload
  - (b) Ship a Linux ARM64 build (Steam Linux Runtime 3.0 ARM64 "Sniper").
  - (c) Do nothing and run the Windows x86 build through Proton+FEX. The Steamworks SDK has had Android and Linux ARM64 libraries since 1.63.
  - https://partner.steamgames.com/doc/steamhardware/steamframe/engines/custom
- **Engine guidance (Unity):** target Android with **Unity's OpenXR plugin**, and "disable all Meta XR and Meta Quest OpenXR features". The settings are:
  - minimum API 29/30, IL2CPP, ARM64, Vulkan recommended (OpenGL allowed);
  - controllers appear as Oculus Touch by default;
  - Valve's `com.valvesoftware.openxr.utils` package includes "Lepton Validation".
  - The page also notes: "uncached GPU buffer access is extremely slow under current FEX TSO settings", which affects Windows x86 builds via Proton.
  - https://partner.steamgames.com/doc/steamhardware/steamframe/engines/unity
- **Lepton release dates:** Lepton (app 3029110) and FEX became public Steam apps in early August 2026. Lepton was open-sourced on 2026-09-11 at https://gitlab.steamos.cloud/frame-public/lepton.
  - Its root filesystem uses Waydroid, Anbox, Halium and Hybris components, and the host Mesa/Zink drivers are mounted in.
  - Its README does **not** mention Quest/Horizon content: "Most users should use Lepton provided by the Steam Client itself."
  - https://mixed-news.com/en/valve-open-sources-lepton-android-container-steam-frame/
- **Badge statistics:** 52 of the first 130 badge-certified titles run through `lepton-stable`, meaning they are Android builds, and 67 run through Proton. Examples of Android depots include Moss VR, RUMBLE and Real VR Fishing. Valve rated The Lab "Unsupported" for graphics performance under ARM64 Proton.
  - https://vr.org/articles/steam-frame-lepton-android-runtime-52-of-130-certified-2026

### Reported by community reverse-engineering (FramePort docs, SteamOS builds 20260922 to 0.4.5)
Source: https://github.com/spoopyghosty0/frameport/blob/main/docs/FRAME_RUNTIME.md

**Compatibility tools**
- ARM64 compat tools are registered from "Steam Frame ARM64 Compat List" (app 3043620). They are `proton_11-arm64` (requires Steam Linux Runtime 4 arm64), `proton-experimental-arm64`, and `fex` (3127680).
- None of them are installed by default. They are downloaded on demand.

**Proton and VR**
- Proton sets up VR (vrclient/wineopenxr) only when `SteamGameId` is set.
- The **Linux SteamVR OpenXR runtime accepts only OpenXR 1.0**. Proton 11's `proton_vrhelper` requests 1.1, so "without help VR never starts for Proton games": they run as a flat window.
- FramePort works around this with an OpenXR layer that retries the create call as 1.0 (checked on SteamOS 0.4.2, 2026-09-29). Valve may have fixed this since. **[?]**

**Graphics stack**
- The GPU drivers are Mesa **Turnip (Vulkan)**, and **GLES runs via Zink** (GL on Vulkan).
- Valve injects foveation (`VALVE_fdm_injection`) and render-pass-optimizer Vulkan layers.

**Lepton container**
- It runs **Android 11 (API 30)**, is **64-bit only (no AArch32)**, and runs apps headless (only OpenXR output reaches the headset).
- Logs are mirrored to `~/.local/share/Steam/logs/lepton-logcats/`.

**OpenXR runtime as Android apps see it**
- It is **OpenXR 1.0 only**.
- Present extensions include `KHR_android_create_instance`, `KHR_vulkan_enable2`, `KHR_opengl_es_enable`, `FB_display_refresh_rate`, `FB_space_warp`, `EXT_hand_tracking` (synthesized from the controllers) and `VALVE_frame_controller_interaction`.
- **Missing:** `FB_passthrough`, the scene/spatial-entity extensions, `KHR_convert_timespec_time`, and cylinder/cube/equirect layers (only quad and projection layers exist).
- GLES swapchains are only `GL_SRGB8_ALPHA8`/`GL_SRGB8` with 1 sample.
- The display runs at 72 Hz by default.

## 2. Android / Quest APK support

### Confirmed
- **Valve's statements:** Valve told The Verge the Frame supports "the same APKs" developers already use for mobile and Quest. A Valve engineer said such builds "will just work". **This applies to developer-supplied Android builds on Steam.** It is not a promise that arbitrary stock Quest APKs run.
  - https://9to5google.com/2025/11/12/valve-bringing-android-games-to-steam-alongside-new-hardware/
  - https://www.androidauthority.com/valve-android-games-steam-3615355
- **Sideloading:** UploadVR reports the Frame can run Android APKs (including browser-downloaded ones) as long as they don't need Google Play Services.
  - https://www.uploadvr.com/valve-steam-frame-official-announcement-features-details
- **Required XR API:** Valve's docs assume **Khronos-standard OpenXR via Unity's OpenXR plugin** with Meta features disabled. They never mention VrApi, the Oculus XR plugin, or the Meta Platform SDK.
  - https://partner.steamgames.com/doc/steamhardware/steamframe/engines/unity
  - https://partner.steamgames.com/doc/steamhardware/steamframe/engines/custom

### Reported (community)
Sources: Frame Control PR #20 (https://github.com/saphid/frame-control/pull/20) and FramePort COMPATIBILITY/PLAYBOOK (https://github.com/spoopyghosty0/frameport/tree/main/docs).

**Why stock Quest APKs fail**
- Lepton launches only `MAIN`+`LAUNCHER` activities. Quest apps use `com.oculus.intent.category.VR`, so they exit with "APP_ACTIVITY is empty" until LAUNCHER is added and the APK is re-signed.
- Apps requesting OpenXR 1.1 fail with `XR_ERROR_API_VERSION_UNSUPPORTED`. **Unity retries at 1.0 and recovers**; native apps do not.
- Fixed refresh-rate requests can fail, because only the current rate is offered.

**What OVRPort does**
- OVRPort (https://github.com/ovrport/app, GPLv3, originally built for Pico) replaces the APK's Meta OpenXR loader with its own dispatcher. It also replaces `libovrplatformloader.so` with its own Meta Platform SDK loader.
- Upstream README: "to get a Quest game running on a different headset, the app has to strip away some entitlement checks".
- An open-source replacement for its closed dispatcher also exists: https://github.com/Molier/openxr-dispatcher-open

**FramePort results**
- FramePort wraps OVRPort with a "FrameBridge" OpenXR adapter that emulates passthrough, cylinders and so on, plus per-game patches.
- It lists about 80 Quest titles as working, including **Unity/OVRPlugin titles**: Beat Saber, Pistol Whip, I Am Cat, Lucky's Tale, Walkabout Mini Golf, Job Simulator and Waltz of the Wizard.
- Failures it lists:
  - 32-bit-only APKs;
  - some Zink/Turnip driver crashes;
  - **games that hard-check Meta entitlement**: "FramePort doesn't bypass entitlement checks". That note is in the Rift/PC section; the Quest path goes through OVRPort's loader, which answers entitlement itself.
  - Meta store/DLC buttons crash, e.g. Phantom: Covert Ops.
- https://github.com/spoopyghosty0/frameport/blob/main/docs/GAMES.md
- **Known Unity + Oculus XR plugin + GLES issues and their fixes**, from the FramePort PLAYBOOK:

| Symptom | Fix |
|---|---|
| Multisampled render-to-texture on Zink → `DEVICE LOST` / hangs | `frame.unity_no_msaa`, `frame.unity_runtime_msaa_off` (patches `OVRDisplay.get_recommendedMSAALevel`) |
| One eye grey with single-pass multiview on GLES | `frame.unity_multipass` |
| Cube-map OVROverlay swapchains refused | — |
| Unity text fields close because there is no Android IME | `frame.unity_text_input` |
| Haptics OOM in older OVRPort | fixed in OVRPort |
| Missing `ovr_*` symbols in the platform loader | `frame.ovrstubs` |
| Hand poses lag because of an XrTime/CLOCK_MONOTONIC offset | — |

## 3. Developer and sideload access

### Confirmed (Valve)
Sources: https://partner.steamgames.com/doc/steamhardware/steamframe/setup, https://partner.steamgames.com/doc/steamframe/adb_lepton and https://partner.steamgames.com/doc/steamframe/loadgames

- **Developer Mode:** Steam Settings → System → Enable Developer Mode. This "will allow you to **ssh**, **adb**, and **rdp** into your headset". You then set a user password under Developer → Set User Password.
- **adb:** adb over USB reaches the **native Linux OS**. Android adb is the **Lepton container on TCP 5555**:
  - Wi-Fi: `adb connect frame`.
  - USB: `adb forward tcp:5555 tcp:5555` then `adb connect localhost:5555`.
  - A Lepton container must be running, either from "Lepton Development" (app 3056000) or any Android game.
  - After that, `adb install x.apk` works.
- **SteamOS Devkit Client:** pair it under Settings → Developer → Pair new host. "Title Upload" then accepts an APK (runtime Android), a Linux ARM64 binary (SLR 3.0 ARM64) or a **Windows .exe (runtime Steam Play/Proton)**. Uploaded titles appear as "Devkit Game: …" in the Library under Non-Steam. This is an official path for running arbitrary Windows or Android builds on the headset.

### Reported
- **Desktop and shell access:** the SteamVR dashboard → "Launch a program" → Desktop gives a KDE Plasma desktop with Konsole. `sshd` must be enabled by hand (`sudo systemctl enable --now sshd` after `passwd`).
  - https://github.com/spoopyghosty0/frameport (README, FRAME_RUNTIME.md)

## 4. Precedent

- **Developer-ported Quest Unity games running officially via Lepton [C]:**
  - Pistol Whip, Job Simulator, SUPERHOT VR and Moss — the Frame's Steam library versions of these are APKs run by Lepton (the Pistol Whip/Job Simulator/SUPERHOT detail is reported by FramePort);
  - Waltz of the Wizard, Real VR Fishing, Pavlov Shack and Table Space.
  - These were rebuilt by their developers, presumably on Unity OpenXR, not stock Quest APKs.
  - https://vr.org/articles/steam-frame-lepton-android-runtime-52-of-130-certified-2026
- **Stock Quest APKs patched by the community [R]:**
  - About 80 titles via FramePort/OVRPort: patch (loader and platform loader replaced, LAUNCHER added, re-signed), install via adb, add a Steam shortcut. Many are Unity IL2CPP + OVRPlugin on GLES.
  - Open Brush (Quest build) reached FOCUSED with only the LAUNCHER fix plus a 1.1-to-1.0 OpenXR layer (Frame Control).
- **Windows PC VR via Proton on the device [R]:**
  - FramePort lists **SUPERHOT VR (PC)** and **Rick and Morty (PC)** as working.
  - These required FramePort's OpenXR 1.0 retry layer at the time: Rick and Morty ran flat without it.
  - The tool calls this path "experimental".
  - Oculus-Platform-SDK PC builds crash, because `LibOVRPlatform64_1.dll` is missing.
- **Blaston specifically [?]:** no report found of Blaston (`com.resolutiongames.ignis`, Steam app 1427890) on the Frame by either path.
  - Blaston's Steam appinfo has only a Windows x64 depot and no Android depot.
  - No Frame compatibility entry was visible in public appinfo when checked on 2026-10-10.

## 5. What we know about our two Blaston builds (from this repo)
- **Quest APK** (`backup/quest/2.3.3.302372/base.apk`, 692 MB):
  - `lib/arm64-v8a` only. It contains `libOVRPlugin.so`, `libOculusXRPlugin.so`, `libopenxr_loader.so` (Meta's), `libovrplatformloader.so`, `libil2cpp.so`, `libunity.so`, `libbhaptics-native-lib.so`, `libopus_egpv.so` and `libwebrtc-audio.so` (Photon Voice).
  - **No `libvrapi.so`.** That means OVRPlugin runs on its OpenXR backend, which is the case OVRPort and FrameBridge handle best. It also avoids the `vrapi_stub` crash class.
- minSdk/targetSdk 32: fine for Lepton (Android 11 / API 30); FramePort notes "minSdk ≤ 32 … is fine".
- Renderer is GLES, so it would run on **Zink** on the Frame. This is the main graphics risk: MSAA, multiview, and strict GLSL.
- **Steam build:** Unity 6000.2 IL2CPP x64 using OpenVR (XRSDKOpenVR) and D3D11. On the Frame that becomes FEX x86-to-ARM64 + Wine/Proton + DXVK D3D11-to-Vulkan + Proton's vrclient bridged to the ARM64 SteamVR. Steam auth works natively because the real Steam client runs on the headset.

---

## 6. Recommendation

### Path A: Steam/Windows build locally via Proton + FEX (quick test, zero modification)
**Steps**
1. On the Frame, install Blaston from the Steam library. If the client only offers Stream, force a compat tool (Properties → Compatibility → Proton 11 ARM64), if the Frame UI exposes that. **[?]**
2. Alternatively, copy `C:\Program Files (x86)\Steam\steamapps\common\Blaston` and upload it with the **SteamOS Devkit Client**: runtime Steam Play, start command `Blaston.exe`.
3. Watch the logs. Valve's Proton docs don't cover VR, so check whether OpenVR starts or the game runs flat. If it runs flat, the OpenXR 1.1 helper issue is the likely cause; FramePort's PC-VR install applies its `pcvr.xr_timefix` layer.

**Pros**
- No patching.
- Steam identity and PlayFab Steam login still work, which helps our own backend later.

**Risks**
- Proton VR on the Frame was immature as of late September (the OpenXR 1.0-only runtime).
- Unity 6 x64 IL2CPP CPU work goes through FEX (−10–20%). D3D11 goes through DXVK on Turnip, and the TSO/GPU-buffer slowness affects Unity particles.
- Likely below 72 fps at Valve's resolution target **[S]**. Even The Lab was rated Unsupported.
- Devkit-uploaded titles may not get `SteamGameId`, and Proton then skips VR setup.

### Path B (most promising): Quest APK via OVRPort/FramePort + Lepton
**Steps**
1. Enable Developer Mode on the Frame and set a password. Pair FramePort (or do it by hand: ssh + Lepton Development + `adb connect frame`).
2. Feed `base.apk`, plus any OBB/asset data from `backup/quest/.../sdcard_data` if the game needs it, to FramePort. It runs OVRPort, which:
   - swaps `libopenxr_loader.so` for its dispatcher and FrameBridge;
   - swaps `libovrplatformloader.so` for OVRPort's Platform SDK loader (no Meta entitlement or account);
   - adds LAUNCHER;
   - lowers minSdk;
   - re-signs.
   FramePort then installs it and adds a Steam shortcut.
   - Manual equivalent: OVRPort CLI, then `adb install`, then a non-Steam shortcut with the Lepton runtime via the Devkit Client.
3. Apply the Unity/GLES recipes when symptoms appear: `frame.unity_no_msaa` / `unity_runtime_msaa_off` (Zink DEVICE LOST), `frame.unity_multipass` (one grey eye), and `frame.unity_text_input` (name entry).
4. Handle identity:
   - With OVRPort's loader, `ovr_User_GetLoggedInUser`, `GetUserProof` and the entitlement calls return OVRPort's stubbed answers, not a real Meta identity. What exactly they return is **[?]**. Blaston's login to auth.resgam.com, PlayFab and Mercury will therefore fail against official servers.
   - This fits our plan: the replacement backend should accept the stubbed Meta user id or nonce, or a deterministic custom id.
   - Alternatively, patch the IL2CPP login code to use PlayFab CustomID. We already have the dump-quest symbols.
   - Do **not** rely on official servers on the Frame.
5. Validate the remaining features:
   - **Photon Voice microphone:** whether Lepton passes the mic into the container is **[?]**. Lepton's Android audio stack is shared with the host per Valve, but mic capture has not been documented.
   - bHaptics library (harmless if absent).
   - Controller mapping: Touch emulation is the default, so it should be fine.
   - 72 Hz default refresh.
   - Any OVROverlay cubemap or cylinder layers (FrameBridge emulates cylinders, refuses cubes).

**Why this path**
- It is native ARM64 with no x86 translation, and the content is already tuned for a mobile Snapdragon (Quest 2/3 class). Snapdragon 8 Gen 3 is faster than the Quest 3's XR2 Gen 2. **[S]**
- It is the same engine and plugin combination as many reported-working titles.

**Main risks**
- Zink GLES bugs.
- OVRPlugin 1.79 functions OVRPort doesn't implement (fixable with stubs).
- Platform SDK calls that never answer: Blaston may wait on Meta login, friends or IAP. FramePort's `frame.ovr_trace` diagnoses this.
- Microphone.
- Community tools change quickly. The original FramePort repo under `austinv11/frameport` now returns 404; the active one is `spoopyghosty0/frameport`, created 2026-10-02.

### Not recommended / long shots
- **Rebuilding Blaston with Unity's OpenXR plugin** (Valve's official path) needs the source project. That is not available to us.
- **Swapping the Oculus XR plugin for the OpenXR plugin inside the IL2CPP binary** is impractical. OVRPort achieves the equivalent at the native-library level.
- **Linux ARM64 build:** does not exist.

### Overall
Spend 30 minutes on Path A for a free data point. Make **Path B the primary track**, and design the replacement backend's auth so it does not depend on genuine Meta user proofs, because neither the Frame nor OVRPort can supply them.

---

## Open questions / unknown as of 2026-10-10
- Whether Valve's current SteamOS or SteamVR fixed OpenXR 1.1 support (both the Android and Linux runtimes were 1.0-only in late September).
- Whether Lepton exposes the microphone to Android apps.
- What OVRPort's platform loader returns for `ovr_User_GetLoggedInUser` and `ovr_User_GetUserProof`. Check its loader exports and test with a logcat trace.
- Whether the Frame's Steam UI lets users force Proton for an Unknown-badge Windows VR game, or always defaults to streaming.
- Any first-hand Blaston report on the Frame. None found.

## Source index
- Valve Steamworks docs:
  - Unity: https://partner.steamgames.com/doc/steamhardware/steamframe/engines/unity
  - Custom engines: https://partner.steamgames.com/doc/steamhardware/steamframe/engines/custom
  - Setup: https://partner.steamgames.com/doc/steamhardware/steamframe/setup
  - adb over Lepton: https://partner.steamgames.com/doc/steamframe/adb_lepton
  - Loading games: https://partner.steamgames.com/doc/steamframe/loadgames
  - Compatibility layers: https://partner.steamgames.com/doc/steamhardware/steamframe/compatibility
  - Badges: https://partner.steamgames.com/doc/steamhardware/steamframe/compat
  - APK upload: https://partner.steamgames.com/doc/steamhardware/steamframe/apk_upload
- Lepton source: https://gitlab.steamos.cloud/frame-public/lepton
- Press:
  - UploadVR announcement: https://www.uploadvr.com/valve-steam-frame-official-announcement-features-details
  - 9to5Google (2025-11-12): https://9to5google.com/2025/11/12/valve-bringing-android-games-to-steam-alongside-new-hardware/
  - 9to5Google (2026-09-18): https://9to5google.com/2026/09/18/valves-open-source-lepton-brings-android-games-to-the-1059-steam-frame/
  - Mixed News, Lepton open-sourced: https://mixed-news.com/en/valve-open-sources-lepton-android-container-steam-frame/
  - Hardware Busters, Lepton and FEX on Steam: https://hwbusters.com/news/valve-ships-lepton-and-fex-on-steam-steam-frames-software-stack-goes-public/
  - VR.org, translation layers: https://vr.org/articles/valve-lepton-fex-steam-frame-translation-layers-2026
  - VR.org, 52 of 130 certified: https://vr.org/articles/steam-frame-lepton-android-runtime-52-of-130-certified-2026
  - VR.org, SteamOS on Android handhelds: https://vr.org/articles/steam-frame-steamos-android-handhelds-rocknix-lepton-2026
  - SteamDeckHQ launch: https://steamdeckhq.com/news/the-steam-frame-officially-launches-available-from-1059/
  - GamingOnLinux, 200+ Verified: https://www.gamingonlinux.com/2026/10/theres-now-over-200-steam-frame-verified-games/
- Community:
  - FramePort: https://github.com/spoopyghosty0/frameport (docs: FRAME_RUNTIME.md, COMPATIBILITY.md, GAMES.md, PLAYBOOK.md)
  - OVRPort: https://github.com/ovrport/app
  - OVRPort fork: https://github.com/Android-XR-Bridge/OVRPort
  - Frame Control PR #20: https://github.com/saphid/frame-control/pull/20
  - openxr-dispatcher-open: https://github.com/Molier/openxr-dispatcher-open
  - ovrplugin-openxr-shim: https://github.com/daniel-lynch/ovrplugin-openxr-shim
  - FrameLoad: https://github.com/Crypto90/frameload
