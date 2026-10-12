# Blaston on Steam Frame: working setup (2026-10-10)

Status: **the Quest APK runs natively on the Frame through Lepton at 144 Hz, 2160×2160 per eye** (measured on the start screen; gameplay still to be verified).

## Pipeline
1. Quest APK `backup/quest/2.3.3.302372/base.apk` → copy in `frame/games/Blaston/`.
2. FramePort 0.12.0 (`external/frameport-venv`, toolchain in `%LOCALAPPDATA%\FramePort\tools`: OVRPort 1.2.5, JRE 21, apksigner):
   `frameport scan frame/games/Blaston` → `frameport build com.resolutiongames.ignis` → `frameport install com.resolutiongames.ignis` → `frameport test com.resolutiongames.ignis`.
   Output APK: `%LOCALAPPDATA%\FramePort\output\Blaston\com.resolutiongames.ignis.apk` (OVRPort conversion, FrameBridge OpenXR adapter, LAUNCHER entry, Unity text-input fix, haptic fix; re-signed with the per-package key in `overport-workspace/signatures`).
3. Frame access: paired at `steamos@<frame-ip>` with FramePort's key `%LOCALAPPDATA%\FramePort\ssh\id_ed25519`. The bootstrap's key append didn't take at first; it was re-added from Konsole over xrdp. Transfers use the Frame's own hotspot (<frame-hotspot-ip>).

## Performance settings
- FrameBridge: `frameport settings com.resolutiongames.ignis refresh_rate=144 scale=1.25` (1728 recommended × 1.25 = 2160 = panel).
- **SteamVR per-app refresh cap**: the runtime only offers rates up to `steam.app.<id>.preferredRefreshRate` (default 90). Raise it live on the Frame:
  `LD_LIBRARY_PATH=/opt/steamvr/bin/linuxarm64 /opt/steamvr/bin/linuxarm64/vrcmd --set-settings-float steam.app.3021366662.preferredRefreshRate 144`
  (`3021366662` is the key SteamVR used for headless/FramePort launches; the Steam-library shortcut may get its own id, so check `vrserver.txt` → `StartSceneApplicationTransitionFromProcess`.)
- Rendering: Vulkan (not GLES), multiview (swapchain array=2), Turnip/Adreno 750.

## Known issues / next
- The game detects "Oculus_Quest_2" → quality tier `OculusQuest_1` (lowest). Spoof a higher tier and re-measure.
- Identity: OVRPort's platform stub returns a **random Meta user ID every launch** → a new PlayFab account each time.
  Fix: `tools/patch_user_id.py` patches `Oculus.Platform.CAPI.ovr_User_GetID` (libil2cpp.so file offset 0x4410FDC in 2.3.3) to return a fixed ID.
  Pinned ID: **<YOUR_META_ID>** = the user's real Meta ID (main account, same as their Quest; level 23). Earlier test pin was <TEST_ACCOUNT_ID>. Original APK kept in `frame/originals/`; the patched copy in `frame/games/Blaston/` is what FramePort builds from.
  RG token login still fails (empty nonce; telemetry only).
- Frame refresh tests: 144 Hz → GPU 6.07 ms avg vs 6.94 ms budget, 31% reprojected (dips on shooting); 120 Hz session pending stats.
- Warning about Meta Touch Pro bindings (harmless; remapped to Touch).
