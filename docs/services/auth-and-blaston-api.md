# Blaston replacement-server spec: RG auth, api.blaston.com, match repository, telemetry, Photon

Scope: everything **except** Mercury core services (playerdata, matchmaking, user reporting) and PlayFab itself.
Sources:
- static analysis under `dump/` (PC x64 ISIL, C# stubs, xref indexes)
- `dump-quest/xrefs/asm/` (Quest ARM64)
- live captures in `capture/` (Quest session 2026-10-09)

Labels:
- **CONFIRMED**: seen in literals, code or live logs.
- **INFERRED**: an educated guess.

Build analysed: 2.3.3.302372-release (identical game version on PC and Quest).

## TL;DR

| Service | Host | Auth the client sends | Needed for |
|---|---|---|---|
| RG token service | `auth2.resgam.com/authTokens/v2/ignis` (from Mercury config) **and** `auth.resgam.com/authTokens/v2/blaston` (hardcoded asset) | none (identity in the query/path) | Mercury login, telemetry, title-data facade |
| api.blaston.com | `https://api.blaston.com/...` | **none**, except knockout tournaments: `Authorization: <getApiBlastonTokenV1 token>` | Arcade/Bowser hub: tokens, blocks, private rooms, tournaments, Discord wall |
| Match repository | `https://blaston-match-repository-dot-blaston.ew.r.appspot.com/` | `x-auth-token: <getUserTokenV1 token>` | replays, spectator "live matches" list |
| Telemetry / logs | `e.resgam.com`, `log-storage-2.ew.r.appspot.com` | none | nothing, just return 2xx |
| Photon | `ns.exitgames.com`, AppIds in the `PhotonServerSettings` asset | **anonymous**, no custom auth | all multiplayer and voice |

Three different tokens exist. Don't mix them up:
1. **RG auth token**, from the RG token service. The client requires it to start with `"Bearer "`. It is sent as `Authorization` to Mercury.
2. **"user token"**, from PlayFab CloudScript `getUserTokenV1`. It is sent as `x-auth-token` to the match repository.
3. **"Blaston API token"**, from PlayFab CloudScript `getApiBlastonTokenV1`. It is sent raw as `Authorization` to `api.blaston.com/knockoutTournaments` only. RG's own offline/Mercury emulation fills it with the dummy value `"12345"`.

## 1. RG authentication service ("token service")

Assembly `Authentication` (namespace `Fidelity.Authentication`), plus `Assembly-CSharp/RGCommon/ServerClient/IgnisAuthentication`.

### 1.1 Base URLs: there are two, and both are live

| Consumer | Base URL source | Value |
|---|---|---|
| `MercuryServerClientAdapter.LogInCoroutine` → `IgnisAuthentication.Authenticate(tokenServiceUrl)` | Mercury config selector `tokenServiceUrl` | `https://auth2.resgam.com/authTokens/v2/ignis` (live, captured) |
| `TrackingStarter.StartTracking` (telemetry) → `IgnisAuthentication.Authenticate(ClientAuthenticationSettings.tokenUrl)` | ScriptableObject `com.resolutiongames.client-authentication` (Resources) | `https://auth.resgam.com/authTokens/v2/blaston` |
| `BlastonMercuryFacade.InitializeHttpClient/InitializeFactory` → `new AuthenticationFactory(ClientAuthenticationSettings.tokenUrl)` (title data / remote config) | same asset | `https://auth.resgam.com/authTokens/v2/blaston` |

- CONFIRMED: `ClientAuthenticationSettings..ctor` default is `https://auth.resgam.com/authTokens/v2/(gameCode)`. The shipped asset overrides it with `.../v2/blaston` (`dump/settings_assets.txt` line 124).
- CONFIRMED: `IgnisAuthentication.Authenticate(tokenUrl)` = `new HttpClient(logger, new CancellationTokenSource())` → `new HttpAuthenticationClient(httpClient, tokenUrl)` → `new AuthenticationService(client, new PlatformCredentialsProvider())` → `.Start()` (which fires `GetAuthenticationData()` immediately). Source: `dump-quest/xrefs/asm/Assembly-CSharp/RGCommon_ServerClient_IgnisAuthentication.txt`.
- CONFIRMED: the authenticated result is cached in a **static** field (`AuthenticationService.authenticationData`, guarded by the static `SemaphoreSlim authLock`). Every `AuthenticationService` instance in the process therefore shares one token, whichever base URL obtained it first.
  ⇒ INFERRED: a replacement can serve both base URLs from one implementation, with identical tokens. Point both hosts (or both rewritten literals) at the same server.

### 1.2 Endpoints

All are **GET** with no body. CONFIRMED: every `HttpAuthenticationClient.Authenticate*` calls `IHttpClient` interface slot 4 with `(url, headers, callerName)`, which matches `DoGet(url, requestHeaders, callerMethod)`. `HttpClient.DoGet` builds `new UnityWebRequest(url)`, sets method `GET`, adds a `DownloadHandlerBuffer`, applies `SetHeaders`, and sends. Query values are concatenated **raw, with no URL-escaping** (CONFIRMED: plain `String.Concat`, no `EscapeDataString`).

`{base}` = one of the base URLs above, with no trailing slash (the paths start with `/`).

| Platform (enum value) | Request | Extra headers |
|---|---|---|
| Oculus/Quest (0) | `GET {base}/oculus/generate-user-token/{userId}?nonce={nonce}` + `&app_id={appId}` **only if appId != null** | none |
| SteamVR (1) | `GET {base}/steam/generate-user-token?ticket={ticketHex}&app_id={appId}` | none |
| ResolutionGames (2, dev/test) | `GET {base}/resolutiongames/generate-user-token` | `Authorization: Basic base64(ISO-8859-1(username + ":" + password))` |
| Pico (3) | `GET {base}/pico/generate-user-token?access_token={t}&userid={id}&displayname={name}&region={region}` | none |
| Viveport (4) | `GET {base}/viveport/generate-user-token?user_token={t}&app_id={appId}` | none |
| PS5 (5) | `GET {base}/ps5/generate-user-token?authorization_code={c}&account_id={id}&environment={env}` | none |
| Service (6, servers/bots) | `GET {base}/generate-service-token/service-name` | `x-auth-token: {service_token}` |

All of the above are CONFIRMED (literals and concat order from the ARM64 listings `dump-quest/xrefs/asm/Authentication/Fidelity_Authentication_HttpAuthenticationClient__Authenticate*_d__*.txt`).

Parameter sources:
- **Quest**: CONFIRMED (`OculusNonceProvider.PutUserIdAndNonceInParameters`). The client calls `Core.AsyncInitialize` if needed, then `Users.GetLoggedInUser()` → `userId` (the Meta user id, e.g. `<YOUR_META_ID>` in our capture), then `Users.GetUserProof()` → `nonce`. `appId` = `PlatformSettings.MobileAppID` on Android, otherwise `PlatformSettings.AppID`. It polls with `Task.Yield()` against `DateTimeOffset.Now.ToUnixTimeSeconds()` and throws `TimeoutException` when time runs out. The Meta app id is **`2307085352735834`** (CONFIRMED: logcat `calling_app_id=2307085352735834` for `com.resolutiongames.ignis`).
- **Steam (PC)**: CONFIRMED (`SteamTicketProvider.PutTicketInParameters`). It calls `SteamUser.GetAuthSessionTicket(byte[1024], …)`, and `ticket = BitConverter.ToString(buf,0,len).Replace("-","")` (an upper-case hex string). `appId = SteamUtils.GetAppID().ToString()`. The static `timeout` = 10 (INFERRED: seconds).
- **Dev override**: CONFIRMED. If PlayerPrefs has `AUTH_FORCE_USER_NAME_PASSWORD_PLAYER_PREFS_KEY`, the client instead uses username/password from `AUTH_TEST_RG_USER_NAME_PLAYER_PREFS_KEY` / `AUTH_TEST_RG_PASSWORD_PLAYER_PREFS_KEY` against `/resolutiongames/generate-user-token`. ⇒ INFERRED: this is a possible hook for a "log in as anyone" revival client, but it needs the PlayerPrefs set on device.
- **Service**: CONFIRMED. `ServiceTokenProvider` reads the environment variable `service_token`, and logs "Environment variable service_token is absent…" when it's missing. Not used by retail clients (INFERRED).

### 1.3 Response (all platforms)

Parsed with **`UnityEngine.JsonUtility.FromJson<ApiAuthenticationResponse>`** (CONFIRMED), so field names are exact and case-sensitive, and unknown fields are ignored:

```json
{
  "token": "Bearer <opaque-or-JWT>",
  "valid_until": "2026-10-11T21:25:17.000000",
  "user_data": { "user_identity": "<rg user id>", "display_name": "<name>" },
  "tracking_id": "<string>"
}
```

- CONFIRMED (`CreateAuthenticationDataFromApiResponse`): `token` is copied verbatim and `valid_until` → `DateTime.Parse(valid_until)` (current culture, no format string). `user_data.user_identity` → `UserData.userId`, `user_data.display_name` → `UserData.displayName`, and `tracking_id` → `trackingId`. The result is `ResultOk`.
- **CONFIRMED: `token` MUST already start with the literal `"Bearer "`.** `AuthenticatedHttpClient.AddAuthHeader` awaits `fnGetAuthToken()`. For both `AuthenticatedHttpClient(backing, IAuthenticationService)` (`<>c__DisplayClass2_0.<.ctor>b__0`) and `AuthenticationFactory.CreateAuthentication` (`<CreateAuthentication>b__10_0`), that returns `AuthenticationData.token` unchanged. It then checks `token.StartsWith("Bearer ")`. On success it adds the header `Authorization: <token>`; on failure it throws `ArgumentException("Token should be prefixed with 'Bearer '. Token is invalid: " + token)`. Mercury's own `GetQuery/PutQuery/PostQuery` also send `Authorization: <authToken>` raw, with `Accept: application/json`, and no `"Bearer "` literal exists anywhere else in the client.
  ⇒ Return `"token": "Bearer " + <your token>`, and accept `Authorization: Bearer <your token>` on every service that receives it.
- CONFIRMED: `display_name` is what gets logged in `[Authentication] Successfully authenticated user <display_name>` (live: the Oculus username).
- `valid_until`: send **naive UTC ISO-8601** (no `Z`, no offset), e.g. `"2026-10-11T21:25:17.000000"`. This is INFERRED from the sibling PlayFab token's live value `"2026-10-10T21:25:29.543014"` (Python `datetime.isoformat()` style).
  - CONFIRMED: the RG-token expiry check compares against `DateTime.UtcNow`, and .NET compares raw ticks regardless of `Kind`, so a naive-UTC string is compared correctly.
  - INFERRED: a `Z`/offset string would be converted to *local* time by `DateTime.Parse`, which skews expiry by the device's UTC offset.
  - **Note the opposite rule for the PlayFab-issued `TokenResponse`s (§1.6):** those are checked against `DateTime.Now` (local), so there a `Z` suffix is the correct choice.
  - Simplest for a revival: use long lifetimes (≥ 24 h) so the skew never matters.
- CONFIRMED (`AuthenticateService` only): for service tokens the client overwrites `valid_until` with `DateTime.Now.AddDays(…)` (InvariantCulture), so service responses can leave it out.

### 1.4 Client behaviour, expiry and refresh

- CONFIRMED (`HasValidAuthentication`): the token counts as valid while `validUntil > DateTime.UtcNow + 5 minutes`.
- CONFIRMED (`GetAuthenticationData`): the client waits on `authLock`. If the token is valid it returns the cache; otherwise it calls `Authenticate()`, which gets fresh platform credentials (a **new Meta nonce every time**) and calls the platform endpoint again. Because `AuthenticatedHttpClient` calls this before **every** request, refresh is automatic and lazy. There's no refresh-token endpoint.
- CONFIRMED: when `AuthenticationRejected`, the client logs `[Authentication] Authentication was impossible, reason: …`. On an exception it logs `[Authentication] Failed to authenticate user. If this is during test/development, consider using username/password…`.
- CONFIRMED (`HttpClient.DoGet`): any non-success `UnityWebRequest.result` (network error, or HTTP ≥ 400) → `LogError` (`[HttpClient] Got {code} ({error}) on a request to {url}:{body}`) → `RequestException(message, responseCode, body)`. The `Authenticate*` method then wraps it as `AuthenticationException("Could not authenticate oculus user" / "…steam user" / …)`. INFERRED: the exception propagates to the caller (the Mercury login or telemetry start fails), and the next `GetAuthenticationData` retries. No backoff in this layer; `ExponentialBackoffStrategy` exists but is used elsewhere.
- CONFIRMED: `InvalidateCachedCredentials()` resets the static cache (empty token, `ResultOk`).
- PlayFab login itself does **not** use the RG token (CONFIRMED from the live log). Quest = `LoginWithCustomID(<Meta user id>)`, PC = `LoginWithSteam`. The two logins run in parallel at startup.

### 1.5 Replacement-server notes (auth)

- INFERRED: Meta nonces can't be verified without RG's Meta app secret, and Steam tickets need RG's Steam publisher key. A revival server should **trust the claimed id**: Quest `userId` from the path, Steam ticket (or a SteamID decoded from it, see below), and return a token bound to `user_identity = "<platform>:<id>"` or similar.
- INFERRED: for Steam, the hex ticket contains the SteamID64 at a fixed offset in the session-ticket blob (bytes 12–19 of a `GetAuthSessionTicket` ticket, little-endian). A stub can pull it out without contacting Valve.
- `user_identity` is the id Mercury/RG services will see. INFERRED: keep it stable per platform user, because other RG services key data on it.
- `tracking_id`: any opaque string. It's used only as the telemetry tracking id (see §4).

### 1.6 PlayFab-issued tokens (the other two token flows)

The game uses two more tokens. Both come from **PlayFab legacy CloudScript**, not from the RG auth host:

| Token | CloudScript | Client classes | Stored in | Used by |
|---|---|---|---|---|
| "user token" | `getUserTokenV1` | `RG.Ignis.PlayFab.PlayFabApiTokenFacade` / `PlayFabApiTokenHandler` | `ApiTokenData.token`, `.validUntil` | match-repository / `TokenApisHttpComponent` (`x-auth-token` header), `MatchStartAnnouncementsHandler` (see §3) |
| "Blaston API token" | `getApiBlastonTokenV1` | `RG.IgnisBowser.BlastonApiTokenHandler` | `BlastonApiTokenData.authenticationToken`, `.validUntil` | `api.blaston.com` (`Authorization` header, see §2) |

- CONFIRMED: both parse `FunctionResult` with JsonUtility into `TokenResponse { string token; string valid_until; }`. Expected CloudScript return value:
  ```json
  {"token": "<string>", "valid_until": "2026-10-10T21:25:29.543014"}
  ```
  `valid_until` → `DateTime.Parse(s, CultureInfo.InvariantCulture)`. CONFIRMED live: `Got token valid until "2026-10-10T21:25:29.543014"` was received about 1 s after login, so validity is about 24 h.
- CONFIRMED (`PlayFabApiTokenHandler`): state machine `NotLoggedIn → Requesting → Idle` (`Error` on failure), with log `[PlayFab] Get user token state {0} -> {1}`. `Tick` re-requests when `validUntil < DateTime.Now`, or when `requestUpdate` is set. Errors log `Got error when getting user token[ settings], will retry soon` and retry (INFERRED: throttled via `lastRequest` + `PlayFabConnectionSettings`).
- CONFIRMED (`BlastonApiTokenHandler`): enqueues a `CloudScriptInvocationRequest("getApiBlastonTokenV1")` with float field `0x1C` = 30.0 (INFERRED: a 30 s retry/timeout). On failure it logs `[BlastonApiTokenHandler] Failed to get api token. Issuing another set of retries`. `BlastonApiTokenData.HasValidToken()` = `DateTime.Now < validUntil`. Live: invoked at menu load and again on entering the Arcade (Bowser), `should cache? False`.
- **CONFIRMED, important for stubbing:** `MercuryServerClientAdapter.ExecuteCloudScript` (RG's in-client PlayFab-CloudScript emulation for the Mercury backend, not live today) answers these two functions locally:
  - `getUserTokenV1` → `{token: <the RG auth token, MercuryServerClientAdapter.authToken>, valid_until: DateTime.Today.AddDays(1).ToString(InvariantCulture)}`
  - `getApiBlastonTokenV1` → `{token: "12345", valid_until: DateTime.Now.AddDays(5).ToString(InvariantCulture)}`

  ⇒ INFERRED: RG's own intended "no PlayFab" path sends the RG token to the match repository and a **dummy `"12345"`** to api.blaston.com. A revival can make `getApiBlastonTokenV1` return any string, and have api.blaston.com accept it or map it to a player. Our own CloudScript should return e.g. `{token: <signed blob containing PlayFabId>, valid_until: now+24h}`.
- INFERRED: the real server-side CloudScripts probably mint these by calling RG's auth service (the `/generate-service-token` family) with a server secret. That logic can't be recovered, but it doesn't need to be: only the replacement services must agree on the format.

## 2. api.blaston.com ("Bowser"/Arcade backend)

Path conventions below:
- `cs/` = `dump/cs/DiffableCs/Assembly-CSharp/`
- `isil/` = `dump/isil/IsilDump/Assembly-CSharp/`
- `arm/` = `dump-quest/xrefs/asm/Assembly-CSharp/`

### 2.0 Transport and auth

None of these calls use `Fidelity.Authentication.AuthenticatedHttpClient`. They all use raw `UnityWebRequest` / `ClientWebSocket` (CONFIRMED).

| Subsystem | Client class | JSON | Auth sent |
|---|---|---|---|
| tokens, userBlocks | `Bowser.ApiRequestHandler.RequestAsync(url, method, body, queryParams)` | request bodies: Newtonsoft (`JsonConvert.SerializeObject` of anonymous types, so **PascalCase/camelCase exactly as written**); responses: `JObject` (tokens) / `JsonUtility` (blocks) | **none** (CONFIRMED) |
| privateRooms | `Bowser.PrivateRoomService.PerformRequest` | JsonUtility both ways | **none** (CONFIRMED) |
| knockoutTournaments | `RG.IgnisBowser.KnockOutTournament.HttpClient` | JsonUtility both ways | **`Authorization: <token>`** (raw, **no** "Bearer " prefix), token from PlayFab CloudScript `getApiBlastonTokenV1` (§1.6) (CONFIRMED) |
| discord ws and upload | `Bowser.Discord.BowserDiscord` | JsonUtility / multipart | **none** (CONFIRMED) |

`ApiRequestHandler` (CONFIRMED, `arm/Bowser_ApiRequestHandler__RequestAsync_d__2.txt`):
- URL = `url + "?" + join("&", k + "=" + v)` when there are query params. Values are **not URL-escaped**.
- If there's a body, it is uploaded via `UploadHandlerRaw(UTF8(json))`.
- It **always** sets `Content-Type: application/json`, even on a GET.
- Only `result == ConnectionError` throws `APIException(request.error)`. HTTP 4xx/5xx are returned to the caller, which checks the code itself.

Identity: every call uses the **PlayFab player id** (CONFIRMED). The source is `BowserIntegration.GetLocalPlayerId()` = `gameProperties["PlayerId"]` (from `LoginData.playerId`; live value `36587F00EFDEC765`), or `"DefaultId"` when it's missing. Remote players' ids come from the Photon player property `"player_id"`.

Error DTO (CONFIRMED, private rooms): `APIError { long statusCode; string detail; }`, parsed from error bodies. So errors look like `{"detail":"..."}`. INFERRED: the original backend was Python/FastAPI.

Offline switch (CONFIRMED): when static `BowserIntegration.ozoOffline` is true, TokenService returns 10 for everything and the Discord socket isn't started.

### 2.1 Arcade tokens: `Bowser.TokenService`

Base is `https://api.blaston.com/tokens` (CONFIRMED). `{pid}` below = PlayFab id.

| # | Request | Body | Success response | Failure behaviour |
|---|---|---|---|---|
| a | `GET /tokens/Balance?playerId={pid}` | none | `{"amount": <int>}` (read via `JObject["amount"]`, returned as float) | No status check: a non-JSON body throws. 5 tries, no delay, then `APIException("[TokenService] Failed to get amount of tokens")`. The caller logs `Failed to fetch tokens:`. |
| b | `POST /tokens/Balance` | `{"PlayerId":"<pid>","Amount":<int>}` (**PascalCase**, Newtonsoft anonymous type) | `{"amount": <int>}` (INFERRED: the new balance) | 5 tries, no delay. Only logged: `[TokenHandler] Failed to change amount of tokens on user's account:`. |
| c | `GET /tokens/FreeTokens?playerId={pid}` | none | HTTP 200 + `{"freeTokensAvailable": <int>}` | Non-200 → `APIException("failed to GetFreeTokens: {code}: {body}")`. No retry. |
| d | **`GET`** `/tokens/FreeTokens/take?playerId={pid}` | none | HTTP 200 + `{"amount": <int>}` (INFERRED: the new balance) | **409 → `NoTokensAvailableException`** (pool empty). Any other non-200 → `APIException`. No retry. |

All CONFIRMED except where marked. `Amount` is +1 (`TokenHandler.AddTokenToWrist`) or −1 (`TokenSpawner.GrabToken`, spending a token on an arcade machine).

INFERRED semantics:
- `FreeTokens` = how many collectible "area tokens" spawn in the Arcade streets. The live log shows "5 area tokens available".
- `take` moves one token from the free pool into the balance.
- The POST is retried without an idempotency key, so it can be applied twice. A server may want to tolerate that.

### 2.2 User blocks: `Bowser.UserBlockingService`

Base is `https://api.blaston.com/userBlocks/`, **including the trailing slash** (CONFIRMED).

| Op | Request | Success | Failure log |
|---|---|---|---|
| block | `POST /userBlocks/` with body `{"sourceUserId":"<myPid>","targetUserId":"<theirPid>","type":"block"}` | **200 only** | `[UserBlockingService] Failed to block user: code={0} body={1}` |
| unblock | `DELETE /userBlocks/` with **the same JSON body** | **204 only** | `[UserBlockingService] Failed remove user from block list: code={0} body={1}` |
| list | `GET /userBlocks/?source_user_id={myPid}` | 200 + `{"blockedUsers":["<pid>",…]}` | `[UserBlockingService] Failed to get list of blocked users: code={0} body={1}` |

All CONFIRMED. `type` is always `"block"`.

CONFIRMED: `BlockManager.LoadBlockedPlayersAsync` (run on entering a Bar room) **retries immediately, with no delay, until it succeeds**. ⇒ The stub must return `200 {"blockedUsers":[]}`, or the client spins in a tight loop.

INFERRED: the server must accept a DELETE request with a JSON body.

### 2.3 Private rooms: `Bowser.PrivateRoomService` / `PrivateRoomManager`

DTO `PrivateRoomService.PrivateRoom` (JsonUtility; used for both request and response; CONFIRMED):
```json
{"floorId":"1","photonRoomId":"JJz2YtTMVxJjiVMHYMVh4uWh2tYALKv2","accessCode":"8896","customId":""}
```
This example is live (logcat 22:26:46). `photonRoomId` = the **Photon room name** the client then creates/joins. `accessCode` = the 4-digit code players share; it is also used as the Oculus Rich Presence lobby id. `floorId` **must be an integer string**, because the client calls `int.Parse` on it.

| Client op | Request (CONFIRMED) | Response |
|---|---|---|
| `GenerateRoomCode(floorId)`: create a private room | `POST https://api.blaston.com/privateRooms/rooms/` with body `{"floorId":"<n>","photonRoomId":"","accessCode":"","customId":""}` | full `PrivateRoom` |
| `JoinOrCreatePrivateRoom(floorId, customId)`: deep-link "custom group id" | same POST with `customId` set | full `PrivateRoom` |
| `GetRoomName(accessCode)`: join by code | `GET https://api.blaston.com/privateRooms/rooms/{accessCode}` | full `PrivateRoom`; **404** = "room with access code X was not found" |

CONFIRMED error handling:
- Connection error → `APIError(code, "unknown network error")`.
- HTTP ≥ 400 → body parsed as `APIError`, i.e. `{"detail":"..."}`.
- Anything below 400 counts as success.
- There is **no delete/leave endpoint** in the client.

INFERRED server logic:
- POST with empty `customId` → mint a fresh unique 4-digit `accessCode` and a random 32-char alphanumeric `photonRoomId`.
- POST with `customId` set → return the existing room for that `customId`, or create one.
- Expire rooms after a while.

### 2.4 Knockout tournaments: `RG.IgnisBowser.KnockOutTournament.KnockoutTournamentClient`

Base is `https://api.blaston.com/knockoutTournaments`, a mutable static `baseUrl` (CONFIRMED).

Headers (CONFIRMED) are set by `HttpClient.SetHeaders`: `Content-Type: application/json` and `Authorization: <BlastonApiTokenData.authenticationToken>`. If the token is null, the client throws `"Trying to make api call before access credentials are available…"`.

Bodies are uploaded as `Encoding.Default` bytes (INFERRED: UTF-8).

Status handling (CONFIRMED):
- `< 400` → body returned.
- `>= 400` → `[KnockoutTournamentClient] Got {0} ({1}) on a request to {2}:{3}`, then `RequestException`.
- `FixEmptyRequestResult` turns `""`/`"null"` into `"{}"` for every call **except** `ReportStartMatch`/`ReportResult` ⇒ always return a JSON object, at least `{}`.

| Client method | HTTP | Path under base | Request body | Response |
|---|---|---|---|---|
| CreateTournament | POST | `/tournaments` | `{"organizerName","organizerId","networkingRegion","size","gameplayRules"}` | `{"tournamentId":"…"}` |
| GetTournamentById | GET | `/tournaments/{tournamentId}` | – | `SerializableTournament` |
| GetTournamentByAccessCode | GET | `/tournaments/accessCode/{accessCode}` | – | `SerializableTournament` |
| JoinTournament | POST | `/tournaments/{id}/participants` | `{"displayName","userId"}` | `{}` |
| LeaveTournament / KickFromTournament | DELETE | `/tournaments/{id}/participants/{userId}` (same path for both) | – | `{}` |
| GetMyTournaments | GET | `/users/{userId}/currentTournaments` | – | `{"organizedTournaments":[id…],"joinedTournaments":[id…]}` |
| Start / ReCreate / ReportCelebrationPlayed | POST | `/tournaments/{id}/state` | `{"state":"running"}` / `"recreated"` / `"celebrated"` | `{}` |
| ChangeTournamentSize | PATCH | `/tournaments/{id}` | `{"size":n}` | `{}` |
| ReportStartMatch | POST | `/tournaments/{id}/matches/{matchId}/startInfo` | `{"roomCode","networkingRegion"}` | `{}` |
| ReportResult / ForceResult | POST | `/tournaments/{id}/matches/{matchId}/results` | `{"participants":[{"userId","score","isWinner","replayUri"},{…}]}` (player one first) | `{}` |

All rows CONFIRMED. The HTTP verbs come from `IHttpClient` slot order, so they carry a small risk if slot mapping was off.

CreateTournament values (CONFIRMED):
- `size` is always **8** and `gameplayRules` is always `"Classic"`.
- `networkingRegion` = `NetworkingRegion.ToString()`. The full value set is: `None, Best, EU, US, Asia, Japan, Australia, UsWest, SouthAmerica, India, CanadaEast, SouthKorea, Russia, RussiaEast, ChineseMainland, SouthAfrica`.
- `organizerId` / `userId` = PlayFab id.

`SerializableTournament` (CONFIRMED field names):
```text
{ "tournamentId":str, "organizerName":str, "organizerId":str, "networkingRegion":str,
  "latestUpdateTimestamp":str, "size":int, "generation":int, "accessCode":str, "roomCode":str,
  "participants":[{"userId":str,"displayName":str}],
  "rounds":[{"matches":[{"matchId":str,
      "participants":[{"userId":str,"displayName":str,"score":int,"isWinner":bool,"replayUri":str}],
      "roomCode":str,"networkingRegion":str,"startTime":str,
      "isForfeit":bool,"forcedResults":bool,"isProgressByBye":bool}]}],
  "state":"created|running|celebrated", "endTime":str, "gameplayRules":str }
```

How the client reads it (CONFIRMED unless marked):
- `state` mapping: created→SignUp, running→Running, celebrated→Celebrated, anything else→SignUp.
- `rounds[count-3]` = quarter-finals, `[count-2]` = semis, `[count-1]` = final.
- Every match reads `participants[0]` and `[1]`. INFERRED: always send two entries, using `userId:""` for a slot that is still TBD.
- An empty `startTime` means the match hasn't started.
- Time remaining = `DateTime.Parse(endTime) - UtcNow`. INFERRED: send naive UTC.
- `replayUri` = a relative match-repository URI (§3.2), which lets players watch tournament replays.

Client flow (CONFIRMED):
- **In the Bar:** the client polls `GetTournamentById` every **60 s**.
- **In matches:** `KnockoutTournamentHandler` queues `ReportStartMatch`/`ReportResult` and sends them only when `HasValidToken()`. A faulted task is retried, logging `[KnockoutTournament] Retrying request…`. INFERRED: up to about 9 tries.

INFERRED: the server uses the `Authorization` token to tell an organizer from a participant, which is how it distinguishes kick from leave.

### 2.5 Discord bridge: `Bowser.Discord.BowserDiscord`

**WebSocket `wss://api.blaston.com/discord/messages/ws`** (CONFIRMED). The client uses `ClientWebSocket.ConnectAsync` with no query string, no headers, no subprotocol and no auth. `GameStateBar.Start` opens one socket per bar floor.

Client → server (CONFIRMED): exactly **one** message after connecting. Its payload is the UTF-8 bytes of `latestSeenMessage`: `""` on first connect, after that the `updatedAt` of the last message received. INFERRED: it is sent as a binary frame (`messageType=1`), so the server must accept binary as well as text.

Server → client (CONFIRMED): one JSON object per WS message, read in 4096-byte chunks up to `EndOfMessage` and parsed with `JsonUtility.FromJson<CustomDiscordMessage>`:
```json
{"id":"…","htmlContent":"…","htmlHeader":"…","timestamp":"1760000000000","avatarUrl":"https://…","updatedAt":"…"}
```
- `timestamp` **must** be a string holding an Int64 of Unix milliseconds. Anything else throws and drops the connection.
- New `id` → message added (the client keeps at most 20). Known `id` with empty `htmlContent` → message deleted. Otherwise → message updated.
- `avatarUrl` is fetched with `UnityWebRequestTexture`.
- INFERRED: the "html" fields are actually TextMeshPro rich text.

Reconnect (CONFIRMED): on any error the client logs `[BowserDiscord] _SetupWebSocket failed: {0}`, waits 2000 ms and reconnects, resending its cursor. There is no application-level ping.

INFERRED server contract: on an empty cursor, push up to about 20 recent messages. On a non-empty cursor, push everything newer than it. After that, push live create/edit/delete events.

**Photo upload `POST https://api.blaston.com/discord/messages/send`** (CONFIRMED). This is `UnityWebRequest.Post` with `multipart/form-data` and no auth. Form fields:
- `message` = `"{userName} sent a photo from Floor {n} in the Ozo Lounge"`
- `file` = PNG bytes, filename `photo.png`, content type `image/png`
- `upload_public` = `"True"` or `"False"` (`BowserIntegration.IsProduction()`)

The client only checks `request.error` being empty, and doesn't retry.

Stub: return 200 and drop the photo. INFERRED: an optional relay can forward it to a Discord webhook and echo it back on the WebSocket.

---

## 3. blaston-match-repository-dot-blaston.ew.r.appspot.com: replays and the live-match feed

Base is `https://blaston-match-repository-dot-blaston.ew.r.appspot.com/`. This service is a **replay store** (`game-messages/*`) plus a **"matches starting now" feed for spectators** (`match-start-announcements*`). It has nothing to do with chat or news.

### 3.0 Transport: `Ignis.TokenApisHttpComponent` (CONFIRMED)

- GET and POST use `UnityWebRequest`, with headers **`x-auth-token: <ApiTokenData.token>`** and `Content-Type: application/json` (sent on GET too). The token comes from PlayFab CloudScript `getUserTokenV1` (§1.6).
- **Only `ConnectionError` counts as failure.** Any HTTP status, including 4xx/5xx, goes to the success callback with the body text. INFERRED: an HTML error page on a GET then throws inside the JSON parse of that one callback, which isn't fatal.
- There is no timeout or retry in the component; retries are done by the callers.
- `{playerId}` = `LoginData.playerId`. INFERRED: this is the PlayFab id.
- INFERRED: in RG's Mercury mode, `getUserTokenV1` returns the RG auth token (which starts with "Bearer "), so `x-auth-token` would carry `Bearer …`. A replacement should accept the header value with or without a `Bearer ` prefix.

### 3.1 Replay upload: `Ignis.GameMessageUploadHandler`

What gets recorded (CONFIRMED):
- Every networked `GameMessage` of a match. A match begins with an `InitGameMessage`, whose `matchId` becomes the key. Onboarding and story events aren't recorded.
- Each message is written as **one line**: `JsonUtility.ToJson(new SerializedMessage{ id = <TypeName without "Ignis.">, m = JsonUtility.ToJson(message) }) + NewLine`, i.e. double-encoded JSON:
  `{"id":"InitGameMessage","m":"{\"t\":0.0,\"fTc\":0,…,\"matchId\":\"…\",\"sceneIndex\":3}"}`

Upload gate (CONFIRMED):
- Uploads happen only when PlayFab title data key **`GAME_LOG_UPLOAD_SETTINGS`** = `{"upload":bool,"batchSize":int,"secondsToRecordAfterEndOfMatch":int}` has `upload:true`. `batchSize` is actually the number of *seconds* between batches.
- INFERRED: **setting `upload:false` in our title data switches off all part/complete uploads.**

| Request (all CONFIRMED) | Body | Response |
|---|---|---|
| `POST game-messages/parts/{matchId}/{playerId}/{batchId}`, where `batchId` = 6-digit zero-padded counter starting at `000000` | raw newline-separated `SerializedMessage` lines (not JSON, despite the header) | ignored (only logged) |
| `POST game-messages/complete/{matchId}/{playerId}`, sent only after every part of that match is Sent | `{"sender_name":str,"opponent_name":str,"sender_score":int,"opponent_score":int,"sender_player_id":int,"gameplay_rules":"Classic\|Shootout\|WinterClassic\|ScrapperShootout\|None"}` | ignored |

Retries (CONFIRMED): a batch is re-sent every **30 s**, at most **10** times, after which it is `Failed`. A failed part blocks the `complete` call for that match forever. INFERRED: the server should overwrite parts idempotently by key.

### 3.2 Replay download: `Ignis.GameMessageDownloadHandler`

Both requests run only when the token state is `Idle` (CONFIRMED).

| Request | Response |
|---|---|
| `GET game-messages/user/{playerId}/latest` | JsonUtility `{"matches":[{"uri":"game-messages/complete/<matchId>/<playerId>","match_id":str,"sender_name":str,"opponent_name":str,"sender_score":int,"opponent_score":int,"sender_player_id":int,"gameplay_rules":str}]}`. Only `matches[0]` is used, so newest first (INFERRED). `uri` is **relative** and resolved as `base + uri`. |
| `GET {base}{uri}`, normally `GET game-messages/complete/{matchId}/{playerId}` | `text/plain`: the whole replay as `\n`-separated `SerializedMessage` lines. INFERRED: the concatenation of all parts in `batchId` order. Bad lines are skipped. |

All CONFIRMED except where marked.

Callers (CONFIRMED):
- The "latest replay" feature.
- Replay URIs launched from the Bowser hub via PlayerPrefs `LAUNCH_RE_URI_PREF`.
- Knockout-tournament `replayUri`s (§2.4).

Failure is non-fatal: the client logs a warning and calls `HandleErrorLoadingReplay`. With an empty `matches` array nothing happens.

### 3.3 Live-match feed: `Ignis.MatchStartAnnouncementsHandler`

**`POST match-start-announcements`** (CONFIRMED):
- Sent by the **Photon master client** at match start, for non-bot matches, while `ApiTokenData.validUntil > Now`. There's no retry.
- Body is `JsonUtility(MatchStartAnnouncementBase)`:
```json
{"match_id":"…","room_code":"<photon room>","region":"EU","multiplayer_protocol_version":"2.3",
 "match_making_queue":"GlobalRatingPlay","player_one_name":"…","player_one_lp":1500,
 "player_two_name":"…","player_two_lp":1480,"gameplay_rules":"Classic","tournament_access_code":""}
```
- `multiplayer_protocol_version` is the literal `"2.3"`; the arcade build adds `-arcade`.
- The response is ignored.

**`GET match-start-announcements/recent`** (CONFIRMED):
- Polled every **10 s**, only while the player is in spectator mode.
- Response: `{"recent_announcements":[{…all fields above…, "timestamp":"2026-10-10T12:34:56.123456"}]}`.

Client-side filtering of `/recent` (CONFIRMED):
- Entries whose `region` doesn't parse as `NetworkingRegion`, or parses as `None`, are dropped.
- Entries whose `multiplayer_protocol_version != "2.3"` are dropped.
- `timestamp` goes through `DateTime.Parse` and then `SpecifyKind(Utc)`. **A null timestamp aborts the whole list.** INFERRED: send naive UTC.

`match_making_queue` decides which spectator list an entry goes into (CONFIRMED):

| Queue value | List |
|---|---|
| `GlobalRatingPlay` | Ranked Duels |
| `3LossYouAreOut` | Blastzone Challenge |
| `Shootout` | Quick Draw |
| `WinterClassic` | Arctic Blast |
| `ScrapperShootout` | Street Brawl |
| anything else | Friendly |

Clicking an entry joins Photon room `room_code` in `region` as a spectator. INFERRED server logic: keep about the last 10 minutes of announcements, newest first.

---

## 4. Telemetry, logs, cross-promo (stub only)

| Endpoint | Request (CONFIRMED) | What the client needs |
|---|---|---|
| `https://e.resgam.com` | `PUT /ignis/{version}/{userId}/{batchNumber}`. `Content-Type: text/plain`, optionally `Content-Encoding: gzip`. Body: one event per line, `E <unix> <event> k=v …`. `userId` is the RG `tracking_id`/user id, obtained by authenticating against `ClientAuthenticationSettings.tokenUrl` (§1.1). | any **2xx**; the body is never read. On failure events are kept in `telemetry.data` and retried, which is non-fatal. |
| `https://log-storage-2.ew.r.appspot.com/logs/{gameCode}/{category}/{file}` (FidelityLogger, `Content-Type: text/plain`); `/logs/ignis/{app_log\|manual_report\|emote}/{file}` (LogSenderComponent); `/logs/bowser/{product}/{file}` (Bowser LogSender) | all **PUT**, no auth, text body | any 2xx; nothing is parsed and failures are non-fatal |
| `https://xp.resgam.com/` | only a library default. INFERRED: never contacted, because `CrossPromoHandler` overrides `jsonURL` with `storage.googleapis.com/resgam-mercury-cross-promotion/com.resolutiongames.blaston.v2.json`. | nothing |
| cross-promo JSON (GCS) | `GET`, then Newtonsoft `PromotionData` | serve `capture/public/20261009/cross-promotion-blaston-v2.json` as-is; a failure just falls back to the cache |

## 5. Photon (PUN 2.22 Realtime + Photon Voice; Photon Chat is not used)

### 5.1 Settings

The `PhotonServerSettings` asset (`Photon.Pun.ServerSettings`) was decoded from the raw bytes. Quest and PC are byte-identical. CONFIRMED values:

| Field | Value |
|---|---|
| AppIdRealtime | *(RG's app id, redacted; replace with your own Photon app)* |
| AppIdVoice | *(RG's app id, redacted; replace with your own Photon app)* |
| **AppIdChat** | **empty**: Chat isn't configured, and no game code calls `Photon.Chat` |
| AppVersion | `2.3`, overwritten at runtime (below) |
| UseNameServer | true |
| Server / Port | empty / 0, so the default `ns.exitgames.com` is used. That literal (plus `http://ns.exitgames.com:80/photon/n`) is in the `LoadBalancingClient` ctor, inside `global-metadata.dat`. |
| FixedRegion | empty (Best Region) |
| **Protocol** | **UDP** |
| EnableProtocolFallback | true |
| AuthMode | Auth (0) |
| RunInBackground | true |

Runtime overrides (CONFIRMED):
- `RGCommon.Network.Photon.PhotonNetworkConnectionProxy.Connect(ver)` sets `AppSettings.AppVersion = MultiplayerProtocolVersion.GetGameVersionString()` and then calls `ConnectUsingSettings()`. The version string is `"2.3"` in retail, `"2.4"` in the AutoTest build, and has `-arcade` appended in arcade builds.
- PUN appends `_2.22`, so **the wire AppVersion is `2.3_2.22`**.
- **Bowser (the Arcade/bar hub)** reconnects with `AppVersion = "Bowser_v" + gameProperties["MultiplayerProtocolVersion"]` and **`FixedRegion = "usw"`**, hardcoded as `BowserApplication.FIXEDPHOTONREGION`. INFERRED wire value: `Bowser_v2.3_2.22`.
- CONFIRMED: no AppId, server or region value comes from PlayFab title data or Mercury config.

INFERRED: default ports apply (NS 5058, master 5055, game 5056 UDP, plus the TCP fallback).

### 5.2 Authentication: **none (anonymous)**

This corrects the earlier `FINDINGS.md` assumption.
- CONFIRMED: `PlayFabClientAPI.GetPhotonAuthenticationToken` is **never called** by game code. It is referenced only inside the PlayFab SDK, on both PC and Quest.
- CONFIRMED: `PhotonNetwork.AuthValues` is set only in the `PhotonNetworkConnectionProxy` ctor, and both `EntryPoint.Start` and `ArcadeEntryPoint.Start` pass `null` (`xor edx,edx`).
- So there's no `CustomAuthenticationType`, no auth parameters and no UserId. INFERRED: Photon assigns an anonymous GUID UserId.
- CONFIRMED (live Quest log): the client reached `OnConnectedToMaster` → `OnJoinedLobby` with no custom-auth callbacks.
- ⇒ **Our Photon app needs no custom-auth provider and no PlayFab Photon integration.**
- CONFIRMED: Voice (`PhotonVoiceNetwork.Connect`) copies only PUN's `UserId`, uses AppIdVoice and `FixedRegion = PhotonNetwork.CloudRegion`, so it's always in the same region as PUN.

### 5.3 Regions

- CONFIRMED: at startup the client calls `ResetBestRegionCodeInPreferences()` and then `SelectRegion(Best)` (`FixedRegion = null`). That makes it ping every region the name server lists and connect to the best one.
- CONFIRMED (`PhotonRegionSelector`) enum ↔ code mapping: EU=`eu`, US=`us`, Asia=`asia`, Japan=`jp`, Australia=`au`, UsWest=`usw`, SouthAmerica=`sa`, India=`in`, CanadaEast=`cae`, SouthKorea=`kr`, Russia=`ru`, RussiaEast=`rue`, ChineseMainland=`cn`, SouthAfrica=`za`. `eu/*` cluster syntax is OK, and unknown codes are ignored.
- CONFIRMED (live): the official name server returned 13 regions (all of the above except `cn`). Best was `eu` at 66 ms.
- CONFIRMED: the client switches region (disconnect, set `FixedRegion`, reconnect) for:
  - PlayFab matchmaking results ("matched with an opponent in another region, switching to {0}")
  - friend codes, which encode the region
  - spectating (announcement/tournament `region`)
  - `BadPingDetectionHandler`
  - arcade-operator and debug menus
- **Matchmaking is PlayFab Multiplayer Matchmaking** (`RG.Ignis.PlayFab.RatingMatchmakingHandler`), not Mercury (CONFIRMED).
  - Ticket attributes: `Region`, `AcceptedRegions` (from Photon pings), `RematchBlockString`, `DisplayName`, `Character`, `LEAGUE_POINTS_SEASON`.
  - Queues: `GlobalRatingPlay`, `3LossYouAreOut`, `Shootout`, `ScrapperShootout`, `WinterClassic`.
  - ⇒ The regions named in our matchmaking config must exist on our Photon setup.

### 5.4 Rooms

**Ignis match rooms**: only `PhotonNetworkConnectionProxy.CreateRoom` creates them, with these CONFIRMED options:
- `MaxPlayers = 10` (2 players + 8 spectators; `NetworkSettings.MAX_PLAYERS=2`, `MAX_SPECTATORS=8`)
- `IsOpen = true`, `IsVisible = isVisible`
- **`PlayerTtl = 5000`**, `EmptyRoomTtl = 0`, `CleanupCacheOnLeave = false`, **`PublishUserId = true`**
- no custom room properties and no lobby-listed properties
- the client joins lobby **`"Ignis"`** (default type)

Room names and flows:
- CONFIRMED: **ranked/queue matches** are named `"mm_" + <PlayFab matchmaking matchId>` and are not visible. Both clients call `CreateRoom`. INFERRED: the loser of the race gets "game exists" and falls back to `JoinRoom`. Create/join is retried.
- CONFIRMED: **friend matches** use a visible room with a 6-digit numeric code: `((rand(0..15624) << 2 | rules&3) << 4 | region&0xF)`, zero-padded. The code itself carries the region and the rules.
- CONFIRMED: **spectators** join an existing match room by `(room_code, region)`, taken from match-start announcements (§3.3), knockout tournaments (§2.4) or the Bowser friend flow, and occupy the spectator slots.

**Bowser rooms**: `JoinOrCreateRoom(photonRoomName, …)` with `MaxPlayers = GetMaxPlayerCountAtFloor(floor)`, a 4-entry table whose values weren't recovered. Room types (CONFIRMED unless marked):

| Room | Options |
|---|---|
| private | `IsVisible=false`, custom property `{"code":"<accessCode>"}`, name from api.blaston.com `photonRoomId` |
| tournament | `IsVisible=false`, property `{"tour":"<6-char code>"}` |
| public floor | visible, listed through the default-lobby room list (INFERRED naming) |

After joining, Bowser sets `CurrentRoom.PlayerTtl = 1`.

Player properties (Bowser only, CONFIRMED): `player_id` (PlayFab id), `player_name`, `player_avatar`, `player_rank`. Ignis sets none, and NickName isn't used.

**Gameplay traffic**:
- CONFIRMED: Ignis sends `RaiseEvent` with **code 0** for all game messages and **code 1** for spectator pings.
- CONFIRMED: Bowser uses PUN `Instantiate`/`InstantiateRoomObject`, RPCs and ownership transfer, which rely on the standard event cache and master-client behaviour.
- CONFIRMED: **no WebRPC, WebFlags/HttpForward, webhooks, server plugins, FindFriends or SQL lobbies.**

**Voice room** = `<PUN room name>_voice_` on the voice app, in the same region (CONFIRMED).

### 5.5 Serialization and other requirements

- CONFIRMED: `Ignis.PhotonMessageRegistry.Register()` registers **49 custom types, codes 0xCC–0xFF**, and Bowser's `RetroBoxHandler` adds one more. INFERRED: these are opaque to the server, so stock Photon Cloud and Server v5 relay them fine.
- Serialization protocol:
  - INFERRED: GpBinaryV18 on the name-server path (the PUN 2.22 default).
  - CONFIRMED: the direct-to-master path forces GpBinaryV16. That path is unused today, but matters if we skip the name server.
- CONFIRMED: SendRate and SerializationRate are 20/20. Encryption is the default (`PayloadEncryption`). `ExpectedProtocol` is never set.
- Server timestamp and time sync are used, and so are `RejoinRoom`/`Reconnect` with PlayerTtl. Both are standard LoadBalancing features.

### 5.6 Redirect options (INFERRED)

- **Self-hosted Photon Server v5 (LoadBalancing):**
  - Point `ns.exitgames.com` at our name server, through DNS or by patching the 16-char literal in `global-metadata.dat`.
  - Expose region codes for whatever regions we run, **including `usw`** for Bowser.
  - AppIds are ignored by self-hosted servers, but the AppVersion strings still partition players: `2.3_2.22`, `Bowser_v2.3_2.22`, `2.3-arcade_2.22`.
- **Our own Photon Cloud app(s):**
  - The AppIds exist only in the serialized `PhotonServerSettings` asset (`data.unity3d` on PC; `assets/bin/Data/data.unity3d` in the APK). They aren't in `global-metadata.dat`.
  - Swapping them means editing that asset in place with same-length GUIDs, and repacking/re-signing the APK.
  - We need a Realtime app and a Voice app.
  - Note: the free tier is 20 CCU per app.

## 6. Minimum viable stub

Ordered by what blocks play first. Redirection is out of scope here: hosts file plus TLS, or literal patching of `global-metadata.dat` / the settings assets.

1. **Photon.** Our own Realtime and Voice apps, or a Photon Server v5. Anonymous auth. Regions must include the ones our matchmaking hands out, **plus `usw`** (the Bowser hub). MaxPlayers 10, PlayerTtl/rejoin. No plugins or webhooks. *Without this there is no multiplayer at all.*
2. **RG token service**, one handler for both base URLs:
   - `GET /oculus/generate-user-token/{userId}?nonce=…&app_id=…`
   - `GET /steam/generate-user-token?ticket=…&app_id=…`
   - Optionally `/resolutiongames/generate-user-token` (Basic auth).
   - Respond `200 {"token":"Bearer <opaque>","valid_until":"<naive-UTC ISO, +24h>","user_data":{"user_identity":"<platform>:<id>","display_name":"<name>"},"tracking_id":"<uuid>"}`.
   - Trust the claimed id; don't verify nonces or tickets.
   - **The `"Bearer "` prefix is mandatory.**
3. **PlayFab CloudScript** (on our own title) for the two token functions. Both return `{"token":"<string>","valid_until":"<ISO, +24h>"}`:
   - `getUserTokenV1`: INFERRED, e.g. a signed `{playFabId, exp}`.
   - `getApiBlastonTokenV1`: may even be a constant, as RG's Mercury path does with `"12345"`.
4. **api.blaston.com**, needed only for the Arcade/Bowser hub:
   - `GET /userBlocks/?source_user_id=…` → `200 {"blockedUsers":[]}`. **Required, or the client retries in a tight loop.**
   - `POST /userBlocks/` → 200. `DELETE /userBlocks/` → 204.
   - `GET /tokens/Balance?playerId=…` → `{"amount":N}`. `POST /tokens/Balance` → `{"amount":N}` (apply `Amount`).
   - `GET /tokens/FreeTokens?playerId=…` → `{"freeTokensAvailable":N}`. `GET /tokens/FreeTokens/take?playerId=…` → `{"amount":N}`, or 409 when the pool is empty.
   - `POST /privateRooms/rooms/` → a `PrivateRoom` with a fresh 4-digit `accessCode` and a random 32-char `photonRoomId`, echoing `floorId`. `GET /privateRooms/rooms/{code}` → that room, or 404 `{"detail":"Not found"}`.
   - `wss /discord/messages/ws`: accept the connection, read one frame, then stay silent. `POST /discord/messages/send` → 200.
   - `/knockoutTournaments/...`: return 404 or `{}`. The feature degrades, but a real implementation is needed for tournaments (§2.4).
5. **Match repository**:
   - `GET /match-start-announcements/recent` → `{"recent_announcements":[]}`. `POST /match-start-announcements` → 200.
   - `GET /game-messages/user/{pid}/latest` → `{"matches":[]}`.
   - `POST /game-messages/parts/...` and `/complete/...` → 200. Alternatively, set title data `GAME_LOG_UPLOAD_SETTINGS={"upload":false,...}` to suppress uploads entirely.
   - A real replay store means concatenating parts by `batchId` and serving them at `GET /game-messages/complete/{matchId}/{pid}`.
6. **Telemetry and logs**: `PUT` anything under `e.resgam.com/*` and `log-storage-2.ew.r.appspot.com/logs/*` → 204/200. Serve the captured cross-promo JSON statically.

## 7. Open questions and uncertainties

- **The `"Bearer "` prefix.** It is proven from code (the `AddAuthHeader` check, and no other `"Bearer "` literal in the client), but not yet seen on the wire. A single live capture of the auth response would settle it.
- **`user_identity` format** used by RG (Mercury keys player data on it). Unknown, and it only matters if a Mercury replacement must match RG's ids.
- **Which RG auth instance runs first.** The cache is static and shared, so in practice both base URLs see a request only if the first one fails. INFERRED: on Quest, telemetry (`auth.resgam.com/.../blaston`) probably authenticates first. The live log shows a single "Successfully authenticated".
- **Server-side meaning of the knockout `Authorization` token.** Mapping it to organizer or participant is a guess.
- The `IHttpClient` slot → HTTP-verb mapping for the knockout endpoints and the log upload rests on interface slot order. Medium confidence.
- **Bowser `GetMaxPlayerCountAtFloor` values** and the public floor room naming scheme were not recovered.
- **Discord WS frame type.** INFERRED binary; the server should accept both binary and text.
- **What the real `getUserTokenV1` / `getApiBlastonTokenV1` CloudScripts do server-side.** Not recoverable from the client, and not needed.
