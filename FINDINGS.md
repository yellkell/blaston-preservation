# Blaston backend map

Source: the Steam build at `C:\Program Files (x86)\Steam\steamapps\common\Blaston` (Unity 6000.2.0f1, IL2CPP, metadata v31).
Found with `tools/dump_literals.py`, `tools/dump_names.py` and `tools/dump_settings_assets.py`. The raw output is in `dump/`.

## Headline (revised 2026-10-10 after static analysis; detailed specs in `docs/services/`)

The shipped 2.3.3 game runs on **PlayFab + legacy CloudScript + PlayFab Matchmaking + Photon (anonymous) + `api.blaston.com` + the match repository**.
Mercury (RG's own backend) is **mostly dormant**. Only the config selector, a telemetry-only token login and maybe an A/B config fetch run.
A complete `MercuryServerClientAdapter` ships in the client but is never instantiated: `ServerClientAdapterFactory.CreateServerClientAdapter` always builds the PlayFab adapter.

Two revival strategies:
1. **New PlayFab title** (the original plan): recreate the title data, catalog and statistics, rewrite **45 CloudScript functions** (`docs/services/playfab.md`) and recreate the matchmaking queues. Purchases and Steam login can't be carried over (they need RG's publisher keys).
2. **Flip to the Mercury adapter** (likely cheaper): patch one call target so the game uses `MercuryServerClientAdapter`. That adapter runs the former CloudScript logic (XP, ELO, league points, rewards, missions) on the client, so our server only needs a key/value store, stats deltas, inventory/currency, title data and a simple 2-player matchmaker (`docs/services/mercury.md` §B, §E.2). No PlayFab account is needed at all.

Either way: host the config selector + title selector, a token service (it can trust any user id; the token must start with `"Bearer "`), the `api.blaston.com` stubs, the match repository, your own Photon app (swap the AppIds in `PhotonServerSettings` inside `data.unity3d`), and 2xx telemetry stubs (`docs/services/auth-and-blaston-api.md`).

**Corrections to earlier notes:** Photon is anonymous (`GetPhotonAuthenticationToken` is never called). Matchmaking is PlayFab Matchmaking (queues `GlobalRatingPlay`, `3LossYouAreOut`, `Shootout`, `ScrapperShootout`, `WinterClassic`), not Mercury. `C6A22` is RG's **stage** title. An internal debug tool embeds a credential for that stage title. It is deliberately not documented here and must not be used.

**The most valuable capture before shutdown:** the PlayFab login response. Login requests title data, user data, statistics, inventory and currencies with no key filter, so a single captured login response contains all client-visible title data.

## PlayFab title ID: confirmed
- **Default/production title ID = `B0549`**: hardcoded in `RG.IgnisBowser.PlayFab.PlayFabReferenceData.GetDefaultEnvironment()`.
- At startup `RGCommon.PlayFab.PlayFabTitleIdComponent.GetPlayFabEnvironmentFromHttp(loginData, gameName, version)` does
  `GET https://playfab-title-selector.ew.r.appspot.com/<gameName>/<version>` and parses (Unity `JsonUtility`):
  ```json
  {"name": "...", "title_id": "XXXXX", "recommend_version_upgrade": false, "require_version_upgrade": false}
  ```
  On any HTTP error it logs `[PlayFab] Error (...) getting environment using default` and uses `B0549`.
  ⇒ **To move the game onto your own PlayFab title, you only need to answer this one request with your title ID** (or patch the `B0549` literal).
- `C6A22` is used only by an internal tournament admin tool that calls PlayFab **Admin** API (`SetTitleData` / `IncrementPlayerStatisticVersion`, key `TOURNAMENT_SETTINGS`). That needs admin credentials. It isn't part of normal gameplay.

## Notes
- Internal names: "Ignis" (Blaston game code), "Bowser" (Arcade/lobby feature), "Mercury" (Resolution Games' shared backend), "Fidelity" (their shared client SDK).
- Full list of REST paths and the classes that call them: `dump/xrefs/rg_endpoints.tsv`.
- PlayFab SDK has `SkipCertificateValidation` / `CustomCertValidationHook`. Worth checking whether the game enables it. That decides whether a hosts-file redirect plus a self-signed certificate works, or whether the URLs must be patched.
- URL literals live in `global-metadata.dat` and can be rewritten there (same-length or table-adjusted), which redirects the client without touching `GameAssembly.dll`.

## What cannot be recovered after shutdown
Server-side data that never ships in the client: PlayFab **title data**, **catalog/store/bundles**, **CloudScript source**, **statistics definitions**, Mercury remote configs and matchmaking rules. **Capture it from live traffic while the servers are up.**

## Quest build (priority target)

- Package `com.resolutiongames.ignis`, version **2.3.3.302372-release** (versionCode 203302372), the same game version as the PC build. It's a single `base.apk` (661 MB), with no OBB and no remote content: the Addressables catalog has no remote URLs, and the 590 MB `UnityCache` on the headset is just the APK's own bundles unpacked. Backup: `backup/quest/2.3.3.302372/` (APK + `/sdcard/Android/data` + `dumpsys`).
- **The same backend as PC**: default PlayFab title **`B0549`**, the same title selector, Mercury, `api.blaston.com` and Photon.
- **Login chain (Quest):**
  1. Meta Platform SDK gives the user id + a one-time **nonce**.
  2. `GET {auth}/oculus/generate-user-token/<userId>?nonce=<nonce>&app_id=<metaAppId>`. The reply (Unity `JsonUtility`) is
     `{"token": "...", "valid_until": "...", "user_data": {"user_identity": "...", "display_name": "..."}, "tracking_id": "..."}`.
     (`HttpAuthenticationClient.AuthenticateOculusUser`, error text "Could not authenticate oculus user".)
  3. PlayFab **`LoginWithCustomID`** (`PlayFabLoginFacade.LoginWithCustomId`); PC uses `LoginWithSteam`.
  ⇒ For a revival, the replacement auth server can't verify Meta nonces (that needs RG's Meta app secret). It just trusts `userId` and returns a token, and PlayFab CustomID login works on any title we own, with no Meta/Steam integration needed.
- Patching for a revival = rewrite URL literals in `assets/bin/Data/Managed/Metadata/global-metadata.dat` inside the APK, re-sign, then sideload. The installed store copy is signed by Meta's store signature, so the patched one must replace it (uninstall first; game progress is server-side).

### Analysis caveat
Cpp2IL's ISIL output is **wrong for the Quest .so**: it reads code at file offset == vaddr, but the text segment is shifted by 0x4000. The method names are right but the bodies are from other code. Use `dump-quest/xrefs/asm/` (our Capstone-based `tools/arm64_disasm.py`) instead; it decodes at the correct offsets and resolves GOT loads through the `R_AARCH64_RELATIVE` relocations.

## Live observations: Quest session 2026-10-09 (logcat, `capture/quest/`)
- **The live backend URLs differ from the hardcoded ones.** The Mercury config selector (`storage.googleapis.com/resgam-mercury-config-selector`, game code `ignis`, version `2.3.3.302372-release`) currently returns:
  `base=https://playerdata.api.rginfra.dev`, `matchmakingUrl=https://match-making.api.rginfra.dev`, `playerDataUrl=https://playerdata.api.rginfra.dev/playerdata`, `tokenService=https://auth2.resgam.com/authTokens/v2/ignis`, `userReporting=https://user-reporting.api.rginfra.dev/userReporting`.
  ⇒ Redirecting **just the config selector** moves the whole Mercury backend. PC gets the same config.
- The title selector returned `B0549 (Blaston prod)`. Quest login = PlayFab `LoginWithCustomID` with the Meta user id as the custom id. RG auth then answered "Successfully authenticated user <name>".
- **Legacy CloudScript functions called** (via `/Client/ExecuteCloudScript`), which a revival must reimplement:
  `getApiBlastonTokenV1, getCurrentMissionSeasonV1, getCurrentStoryV1, getDecksV1, getInventoryV2, getLeaguePointsSeasonV1, getPlayerSettingsV1, getToolAttachmentsV1, getToolMasteryMissionProgressV1, getUserMessagesV1, setSelectedToolAttachmentsV1, setToolMasteryTrackingV1, updateOculusPushNotificationTokenV1` (from menu + Arcade only; match flow not yet observed).
- Store: Meta IAP products `Blasts_Pack_1..5` (199/499/999/2299/4999 cents → 70/200/450/1160/2850 coins). PlayFab catalog contains `ResolutionSnowball`, which isn't in the game.
- Also loaded from PlayFab: player statistics (10), level/XP, news (10 items), equipped cosmetics, tournament event, rating matchmaker settings.

## Public startup configs (saved in `capture/public/20261009/`)
These are unauthenticated GETs the game makes at every launch, so they're the first things to host ourselves:
- Mercury config: `GET https://storage.googleapis.com/resgam-mercury-config-selector/ignis/<version>/urls`
  → `{"baseUrl","playerDataUrl","matchmakingUrl","tokenServiceUrl","userReportingUrl"}`, currently `*.api.rginfra.dev` + `auth2.resgam.com`.
- PlayFab title selector: `GET https://playfab-title-selector.ew.r.appspot.com/blaston/<version>`
  → `{"name":"Blaston prod","recommend_version_upgrade":"false","title_id":"B0549"}` (gameName is `blaston`; the bool is sent as a string).
- Cross-promo: `storage.googleapis.com/resgam-mercury-cross-promotion/com.resolutiongames.blaston.v2.json`.

## Captured server data: Frame local cache (2026-10-11)
`backup/frame-cache/20261011/`: the Frame build's PlayerPrefs, with **45 cached CloudScript responses** decoded to JSON in `cloudscript/`. Includes:
- `getCurrentMissionSeasonV1`: season `2026_10` (2026-10-01 → 11-01) with the full mission list (ids, qualifiers such as tool names, `amountToComplete`).
- `getLeaguePointsSeasonV1` (29 KB), `getToolMasteryMissionProgressV1` (37 KB), `getToolAttachmentsV1`, `getInventoryV2` (`items`, `virtualCurrencies`), `getDecksV1`, `getCurrentStoryV1`, `getPlayerSettingsV1`, `getUserMessagesV1`, `getPlayerInfoV1` (opponents), and `updateMissionProgressV1` replies.
These are real server response shapes and content for the revival server. Each launch refreshes them, so copying this file periodically archives new seasons.
