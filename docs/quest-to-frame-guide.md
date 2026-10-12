# Blaston: from a Quest 3 to a Steam Frame (native, your own account)

The exact process we used on 2026-10-10/11. Result: Blaston runs natively on the Frame (Android build in Valve's Lepton
layer), 120 Hz at 2160×2160 per eye, logged into **your** Blaston account, in the Steam library as "Blaston".

Tested with Blaston **2.3.3.302372** (Quest), FramePort **0.12.0**, OVRPort **1.2.5**, SteamOS **0.4.5**.
All paths are relative to the repo root.

---

## What you need
- The Quest 3 with Blaston installed and **Developer Mode** on (Meta Horizon phone app → Devices → Headset settings →
  Developer Mode; this needs a verified developer account at developers.meta.com).
- A USB-C **data** cable, and `adb` (Android SDK platform-tools; ours is in `%LOCALAPPDATA%\Android\Sdk\platform-tools`).
- The Steam Frame in **Developer Mode** (Steam → Settings → System → Developer Mode) and on the **same Wi-Fi** as the PC,
  with a user password set (Settings → Developer → Set User Password).
- On the PC: Python 3.11, and the tools in this repo (`external/frameport-venv`, `tools/patch_user_id.py`).

---

## Step 1: Copy Blaston off the Quest 3
1. Plug the Quest into the PC, put it on, and accept **"Allow USB debugging"** (tick "Always allow").
2. Check it's visible, and find the package:
   ```bash
   adb devices -l
   adb shell pm list packages | grep resolutiongames.ignis
   adb shell pm path com.resolutiongames.ignis
   ```
3. Pull the APK (Git Bash: prefix with `MSYS_NO_PATHCONV=1` so device paths aren't mangled):
   ```bash
   MSYS_NO_PATHCONV=1 adb pull /data/app/…/com.resolutiongames.ignis-…/base.apk backup/quest/<version>/base.apk
   ```
   Blaston is a single APK with no OBB, and all its content is inside it.
4. Optional backups: `adb pull /sdcard/Android/data/com.resolutiongames.ignis` and
   `adb shell dumpsys package com.resolutiongames.ignis > dumpsys_package.txt` (version info).

## Step 2: Find your Meta user ID (your Blaston account)
Blaston's Quest build logs into PlayFab with your **Meta user ID** as the account key. Record the game's log while it logs in:
```bash
adb logcat -c
adb logcat -v threadtime > capture/quest/logcat.txt
```
Launch Blaston on the Quest, wait for the main menu, stop the logcat with Ctrl+C, then search for:
```
[PlayFab] : Login in with custom id <YOUR_META_ID>
```
That number is your account (`<YOUR_META_ID>` below). Keep the log private, because it contains session tokens.

## Step 3: Pin your account into the APK
OVRPort (the Quest→Frame converter) replaces Meta's platform library with a stand-in that returns a **random user ID
every launch**, which would give you a new, empty account each time. We patch Blaston's `ovr_User_GetID` so it
always returns your ID:
```bash
mkdir -p frame/originals frame/games/Blaston
cp backup/quest/<version>/base.apk frame/originals/com.resolutiongames.ignis.apk
python -I tools/patch_user_id.py frame/originals/com.resolutiongames.ignis.apk frame/games/Blaston/com.resolutiongames.ignis.apk <YOUR_META_ID>
```
The script checks the exact original bytes first, and refuses if the APK is a different Blaston version. For a new version,
re-derive the offset: look up `Oculus.Platform.CAPI::ovr_User_GetID` in `dump-quest/symbols.tsv` after re-running
the analysis for that build, and convert its address to a file offset (the code segment is shifted 0x4000).

## Step 4: Convert for the Frame (FramePort)
```bash
PYTHONIOENCODING=utf-8 external/frameport-venv/Scripts/frameport tools install
PYTHONIOENCODING=utf-8 external/frameport-venv/Scripts/frameport scan frame/games/Blaston
PYTHONIOENCODING=utf-8 external/frameport-venv/Scripts/frameport build com.resolutiongames.ignis
```
`tools install` downloads FramePort's portable toolchain (Java, OVRPort, apksigner) into `%LOCALAPPDATA%\FramePort`.
`build` swaps Meta's OpenXR loader and platform library (OVRPort), adds the FrameBridge adapter and a launcher entry, then
re-signs. Every check should say **PASS** (one WARN about compressed libraries is fine).
Output: `%LOCALAPPDATA%\FramePort\output\Blaston\com.resolutiongames.ignis.apk`.
The signing key is kept in `…\overport-workspace\signatures\`, so later builds install as updates without wiping data.

## Step 5: Pair the Frame with the PC
```bash
PYTHONIOENCODING=utf-8 external/frameport-venv/Scripts/frameport frame pair --timeout 1200
```
It prints a one-liner such as `curl -fsS <pc-ip>:8765/<code> | bash`. On the Frame: **SteamVR dashboard → Launch a
program → Desktop → app menu → System → Konsole**, type it exactly, and press Enter. If Steam asks to install **Lepton**, accept.

Gotchas we hit:
- Use the PC's **home-network IP**. Windows Firewall blocks the pairing server on the Valve dongle's network, which Windows treats as "Public".
- If the key login still fails afterwards, re-add the key from Konsole. Remote desktop to the Frame works (`mstsc /v:<frame-ip>`, log in as `steamos`).
  In Konsole run:
  `mkdir -p ~/.ssh; chmod 700 ~/.ssh; echo '<contents of %LOCALAPPDATA%\FramePort\ssh\id_ed25519.pub>' >> ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys`
- Check with `frameport frame info`.

## Step 6: Install on the Frame
```bash
PYTHONIOENCODING=utf-8 external/frameport-venv/Scripts/frameport install com.resolutiongames.ignis
```
The library shortcut ("Blaston") is added on the next Steam restart. FramePort waits until **no game is running and Desktop
Mode is closed** (including any remote-desktop session), then restarts Steam once by itself.

## Step 7: Full resolution and a smooth refresh rate
1. FrameBridge settings (scale 1.25 takes the 1728 recommended size to 2160 per eye, the panel's native resolution):
   ```bash
   PYTHONIOENCODING=utf-8 external/frameport-venv/Scripts/frameport settings com.resolutiongames.ignis refresh_rate=120 scale=1.25
   ```
2. Raise SteamVR's **per-app refresh cap** (default 90) on the Frame, over SSH:
   ```bash
   ssh -i "$LOCALAPPDATA/FramePort/ssh/id_ed25519" steamos@<frame-ip> 'LD_LIBRARY_PATH=/opt/steamvr/bin/linuxarm64 /opt/steamvr/bin/linuxarm64/vrcmd --set-settings-float steam.app.3021366662.preferredRefreshRate 120'
   ```
   `3021366662` is the shortcut's app id (FramePort prints it at install: "shortcut 3021366662"). It's saved to
   `~/.config/openvr/config/steamvr.vrsettings`.
3. Why 120 and not 144: at 144 Hz the GPU had under 1 ms of headroom and **31%** of frames were reprojected when people shot.
   At 120 Hz only **1.3%** were.

## Step 8: Test and play
```bash
PYTHONIOENCODING=utf-8 external/frameport-venv/Scripts/frameport test com.resolutiongames.ignis --seconds 75
```
Expect `Frame pacing: 120 fps` and, in `%LOCALAPPDATA%\FramePort\logs\…`,
`Login in with custom id <your id>` → `LoggedIn`. Then launch **Blaston** from the Frame's Steam library.
The first launch shows the agreement again (it's stored per account), so accept it.

---

## Notes
- **Privacy:** OVRPort's platform stand-in contacts a third-party server (`ovrp.crx.moe`) for a "logged-in user". Our patch
  makes Blaston ignore that ID, but the request still happens.
- **One headset at a time:** Quest and Frame now log into the same account.
- **Resolution Games' own sign-in** (auth2.resgam.com) fails on the Frame (no Meta nonce). It's only used for telemetry, so play is unaffected.
- **Graphics:** the Quest build applies the same default quality on every headset (its per-device quality profiles aren't
  shipped), so the Frame looks like a Quest 3, only sharper.
- **Don't** use the Steam (Windows) version on the Frame for this. Through Proton and FEX it ran at ~36 fps (81% reprojection).
- **Game update:** pull the new APK (Step 1), re-derive the patch offset (Step 3), rebuild (Step 4), install (Step 6).
