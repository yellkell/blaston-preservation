# Mercury backend: replacement-server spec

Scope: Resolution Games' "Mercury" player-data and matchmaking backend, as used by Blaston (game code `ignis`, build 2.3.3.302372).
Source: static analysis only. The sources are the C# stubs in `dump/cs/DiffableCs/ResolutionGames.Services/Fidelity/MercuryServices/` and `Assembly-CSharp/RGCommon/ServerClient/MercuryServerClientAdapter.cs`, the x64 ISIL in `dump/isil/IsilDump/...`, the logs in `capture/quest/` and `dump/settings_assets.txt`.

Legend: **C** = CONFIRMED (string literal, DTO field, MethodInfo or register trace seen). **I** = INFERRED (educated guess).
`{base}` = `baseUrl`, `{pd}` = `playerDataUrl` (= `{base}/playerdata`), `{mm}` = `matchmakingUrl`, `{gc}` = game code `ignis`.

---

## 0. Read this first: what the build actually uses

| Finding | Evidence |
|---|---|
| **The full Mercury game backend, `MercuryServerClientAdapter`, is compiled in but never instantiated.** `ServerClientAdapterFactory.CreateServerClientAdapter(settings, ignisConfig)` always does `new PlayFabServerClientAdapter(...)`. The Arcade, BayTek and LIV platform factories do the same. Nothing calls the adapter's constructor, and the build has the `RG_PLAYFAB` define. **C** | `dump/isil/IsilDump/Assembly-CSharp/ServerClientAdapterFactory.txt`; the call_xrefs show no caller of `MercuryServerClientAdapter::.ctor`; `TrackingStarter` lists scripting symbols |
| No other game code references the Fidelity *library* services: Friends, Party, SSE/WS listeners, Quests, Ban, Blocking, OnlineStatus, DisplayName, Achievement, PlayerData, Match, MercuryMatchMakingService, IAPShopService, Health. They are shipped SDK code. **C** | grep of IsilDump for their `typeof`, ctor calls and interface names: hits only inside the adapter and SDK |
| The captured Quest session (2026-10-09) has **no** `[Mercury] …` log lines, no SSE, no websocket and no ticket traffic. Matchmaking went through PlayFab and Photon. The "`[Mercury] CreateMatchMakingTicket`" string exists only as a literal in `MercuryMatchMakingService`. **C** | `capture/quest/*.txt` |
| **What the shipped build does hit (live):** (1) the config selector `GET …/resgam-mercury-config-selector/ignis/<ver>/urls`; (2) the token service, through `TrackingStarter → IgnisAuthentication.Authenticate(tokenServiceUrl)` (log line "`[Authentication] Successfully authenticated user …`"); (3) possibly `BlastonMercuryFacade.InitRemoteConfig` (A/B tests). Item (3) uses **hardcoded** `https://playerdata.resgam.com` + `/playerdata/titledata/ignis/<key>`, with a token from `https://auth.resgam.com/authTokens/v2/blaston`. **C** (1, 2); **C** wiring for (3), but whether it fires at runtime is **I** | `IgnisConfigSelector`, `TrackingStarter`, `BlastonMercuryFacade.txt`, `settings_assets.txt` |

**Consequences**
- **Unpatched build:** Mercury is *not* on the critical path for login, menu, matchmaking or match. All of those are PlayFab, Photon and `api.blaston.com`.
- **Patched build:** the adapter is a complete `IServerClientAPI` (PlayFab-shaped) implementation. It runs all the former CloudScript logic client-side: XP, league points, ELO, rewards, missions, story and tool mastery. Its server needs are only **dumb KV storage, an achievement counter store, inventory/currency and a simple matchmaker**. Patching one call target in `CreateServerClientAdapter` to construct `MercuryServerClientAdapter(logger, runner, new JsonParsingHttpClient(new HttpClient()), ignisConfig, ServerClientAdapterFactory.Authentication)` would switch the whole game to Mercury. That is likely far cheaper than reimplementing PlayFab plus CloudScript. Section B specifies what that adapter needs.
- Section C documents the rest of the Fidelity SDK services for completeness. They are needed only if some other RG title, or a future patch, uses them.

---

## 1. Discovery and URL conventions

### 1.1 Config selector (live) **C**
`GET https://storage.googleapis.com/resgam-mercury-config-selector/ignis/<version>/urls` (`ConfigSelector.Get` = `baseUrl + "/" + gameCode + "/" + version + "/" + dataKey`). There is a second selector with version `adhoc`. Both are anonymous.
```json
{"baseUrl":"https://playerdata.api.rginfra.dev","playerDataUrl":"https://playerdata.api.rginfra.dev/playerdata",
 "matchmakingUrl":"https://match-making.api.rginfra.dev","tokenServiceUrl":"https://auth2.resgam.com/authTokens/v2/ignis",
 "userReportingUrl":"https://user-reporting.api.rginfra.dev/userReporting"}
```
`IgnisConfig.URLs` field order is baseUrl, matchmakingUrl, playerDataUrl, tokenServiceUrl, userReportingUrl. `GetConfigSafe` catches exceptions (`Debug.LogException`), and telemetry then runs "without authentication". The selector therefore looks **non-fatal** (I).

### 1.2 How paths are built
- **Fidelity SDK services** use `string.Concat(baseUrl, "/playerdata/<svc>/", gameCode, "<suffix>")`. This was confirmed by register trace on `MatchService.SendResult` and on several `string[]` concats: element order is base, prefix, `gameCode`, suffix, arg. **C**
- **MercuryServerClientAdapter** uses `System.IO.Path.Combine(playerDataUrl, …)`. On Windows/PC this joins with **`\`**; on Quest/Android it uses `/`. Mono's `Uri` normalises `\` to `/` for http(s), but **the server should accept both separators** (I).
- Query strings are **not URL-escaped** in any call site I inspected (no `EscapeDataString`). Display names with spaces or `&` will arrive raw (I). DateTime "o" values can contain `+hh:mm`, which a lenient parser may read as a space.
- Date formats: `AchievementService` uses `"s"` (`2024-05-01T00:00:00`). `LeaderboardService` and the adapter use `"o"` (`2024-05-01T00:00:00.0000000Z`). `PlayerDataService.GetExportableKeys` uses `"yyyy-MM-ddThh:mm:ss"`, which is a **12-hour `hh` bug**. **C**

---

## 2. Transport, auth and error handling

| Aspect | Behaviour | |
|---|---|---|
| HTTP stack | `Fidelity.Authentication.HttpClient` (UnityWebRequest). Verbs `GET/PUT/POST/PATCH/DELETE`. A request with a body gets `Content-Type: application/json`. A non-2xx status throws `RequestException(code, body)` (log "`[HttpClient] Got {0} ({1}) on a request to {2}:{3}`"). | C |
| `IHttpClient` vtable order | 0 `DoPatch`, 1 `DoPut`, 2 `DoPost`, 3 `DoDelete`, 4 `DoGet`, 5 `DoGetAsync` (streaming, used for SSE). | C |
| Auth header (SDK) | `AuthenticatedHttpClient.AddAuthHeader` takes the token string from `AuthenticationService.GetAuthenticationData().token`. If it **`StartsWith("Bearer ")`**, the client adds `Authorization: <token>` verbatim. Otherwise it throws `"Token should be prefixed with 'Bearer '"`. ⇒ **The token service must return `token` already prefixed with `"Bearer "`.** | C |
| Auth header (adapter) | `GetQuery`: `Accept: application/json` + `Authorization: <authToken>`. `PutQuery`/`PostQuery`: `Content-Type: application/json`, `Accept: application/json`, `Authorization: <authToken>`. `authToken` = the same `AuthenticationData.token`. | C |
| Websocket auth | `SocketListener` sets the `Authorization` request header to the `authToken` ctor arg. | C |
| JSON | Newtonsoft (`JsonConvert`). Deserialisation is case-insensitive, so snake_case or PascalCase as listed both work. `JsonParsingHttpClient.Do*<T>` throws `BodyIsNullException` if the body is the literal `null`. **Typed calls must return a non-null JSON value.** | C |
| `SaveOperationResult` | `{"success":bool,"message":string}`. Most SDK writes `await` this and throw `"[Mercury] Failed calling X: "+message` when `success` is false. **Return `{"success":true,"message":""}`.** | C (fields); I (throw-on-false) |
| Identity | The server derives the player from the bearer token. No endpoint carries the caller's own id, except the adapter's opponent lookups. The token's `user_data.user_identity` is the player id that appears in matchmaking `playerids`. | C/I |

Token service (`tokenServiceUrl`, e.g. `…/authTokens/v2/ignis`): `GET {tok}/oculus/generate-user-token/<userId>?nonce=&app_id=`, `/steam/generate-user-token?ticket=&app_id=`, `/pico/…`, `/viveport/…`, `/ps5/…`, `/resolutiongames/generate-user-token` (Basic auth), `/generate-service-token/service-name` (`x-auth-token`). Reply: `{"token":"Bearer …","valid_until":"…","user_data":{"user_identity":"…","display_name":"…"},"tracking_id":"…"}`. **C** (details belong in the auth doc.)

---

## A. Live-path endpoints (unpatched 2.3.3)

| # | Method + URL | Auth | Request | Response | Client use | |
|---|---|---|---|---|---|---|
| A1 | `GET https://storage.googleapis.com/resgam-mercury-config-selector/ignis/<ver>/urls` | none | – | URLs JSON (1.1) | `IgnisConfig` for telemetry auth; adapter factory receives it but ignores it | C |
| A2 | token service (see §2) | platform proof | – | token JSON | `TrackingStarter` → telemetry tracking id | C |
| A3 | `GET https://playerdata.resgam.com/playerdata/titledata/ignis/<key>` | Bearer (from `auth.resgam.com/authTokens/v2/blaston`) | – | raw JSON value of the title-data key | `MercuryTools.RemoteConfig` / A/B tests. The `remote-config-collection` asset looks empty, and `ClientNetworkService` tolerates `404` ("Key possibly does not exist on the server"). | C wiring; I runtime |

---

## B. MercuryServerClientAdapter (dormant PlayFab replacement)

Fields: `baseUrl`(0x30), `playerDataUrl`(0x38), `matchmakingUrl`(0x48), `gameCode`(0x58, the literal `"ignis"`), `authToken`(0xA0), `userId`(0xA8), `cachedOtherPlayerId`(0xB0). Every URL below was traced to these fields.

### B.1 Endpoint table

| Adapter method (PlayFab API it emulates) | Method + URL | Body | Response type → shape | |
|---|---|---|---|---|
| `LogInCoroutine` (LoginWithCustomID/Steam/PlayFab) | token service via `IgnisAuthentication.Authenticate(tokenServiceUrl)` | – | AuthenticationData. Fails on empty `token` or `userId`. | C |
| `LoadTitleDataTask` (GetTitleData; first call after auth) | `GET {pd}/titledata/{gc}/title_data` | – | PlayFab `GetTitleDataResult` → `{"Data":{"<KEY>":"<string>",…}}` | C |
| `GetCurrentTournaments` (login) | `GET {pd}/{gc}/tournament` | – | `Dictionary<string,TournamentSettings>`. The adapter stores it into title data `TOURNAMENT_SETTINGS`. | C |
| `GetUserData` (login, and many CloudScript emulations) | `GET {pd}/playerdata/{gc}/user_data` | – | PlayFab `GetUserDataResult` → `{"Data":{"<KEY>":{"Value":"<string>","LastUpdated":"<date>","Permission":"Public"}},"DataVersion":0}` | C URL/type; I that `user_data` is a reserved "all keys" key |
| display name (login) | `GET {pd}/displayname/{gc}` | – | `Dictionary<string,string>`; reads key **`DisplayName`** (the same object as SDK `GetDisplayNameResponse`: `PlayerId, GameCode, DisplayName, CreatedOn, OnlineStatus, OnlineStatusUpdatedOn`) | C |
| `UpdateUserTitleDisplayName` | `PUT {pd}/displayname/{gc}` | `{"display_name":"<name>"}` (I: dict key literal `display_name`) | `Dictionary<string,string>`: `success` compared ordinally to `"true"`, `message` to `"DisplayNameUnavailable"` ⇒ return **strings** `{"success":"true","message":""}` | C |
| `SavePlayerDataEntry(key, json)` (UpdateUserData, every progress write) | `PUT {pd}/playerdata/{gc}/{key}` | the **raw serialized value** (JSON text) | `Dictionary<string,string>` (return `{"success":"true"}`) | C |
| `GetTitleNews` | `GET {pd}/titledata/{gc}/title_news` | – | PlayFab `GetTitleNewsResult` → `{"News":[{"NewsId","Title","Body","Timestamp"}]}` | C |
| stats read (`QueryAllPlayerStatistics`, GetPlayerStatistics) | `GET {pd}/{gc}/achievement/summary?start_date=<o>&end_date=<o>` | – | `{"achievements":[{"achievement_code":"ELO_RATING","achievement_value":1234.0}]}`. The date range is the current season from `/seasons`; it errors "No current season found!" without one. | C |
| stats write (`UpdatePlayerStatisticsAutoIncrement`) | `PUT {pd}/achievement/{gc}` | `{"achievement_code":"…","achievement_value":<delta float>}` | `Achievement` (any object, e.g. echo) | C |
| seasons (`CacheSeasonsFromService` → SDK `LeaderboardService.GetSeasons`) | `GET {base}/playerdata/{gc}/seasons` | – | `{"seasons":[{"season_id","start_date","end_date","achievement_keys":[{"name","aggregation","custom_data"}]}]}`. On failure the SDK logs "returning dummy seasons" (`mercury_static_leaderboard_seasons`). | C |
| LP leaderboard (`GetLeagePointsSeasonLeaderboard`) | `GET {pd}/{gc}/achievement/leaderboard?achievement_code=LEAGUE_POINTS_SEASON&aggregation_method=Sum&start_date=<o>&end_date=<o>&limit=N&minimum_entries=M` | – | `LeaderboardResponse` `{"leaders":[{"player_id","display_name","rank","achievement_value"}]}` | C literal; I first two path parts |
| own placement (`CacheLeaderboard` → SDK) | `GET {base}/playerdata/achievement/{gc}/placement?achievement_code=&aggregation_method=&start_date=&end_date=&limit=1&minimum_entries=` | – | one `LeaderboardResponseItem` | C |
| `GetInventory` (currencies) | `GET {pd}/{gc}/inventory/get_player_currencies` | – | `{"currencies_balances":[{"currency_code":"BP","balance":0},{"currency_code":"FR","balance":0}]}` (codes seen: `BP`, `FR`, `premium_coins`) | C |
| `GetUserInventory` | `GET {pd}/inventory/{gc}` | – | `{"Items":[{"InventoryItemId":int,"PlayerInventoryId":int,"Name","Description","ItemClass","UsesRemaining":int,"ExpiresOn":date,"Options":{},"Tradeable":bool}]}` (PascalCase) | C |
| `GetCatalogItems` | `GET {base}/playerdata/inventory/{gc}/catalog` | – | `{"items":[{"id","name","tradeable","description","item_class","max_per_player","max_per_title","consumable_count","consumable_seconds","options":{unlockAtLevel,onlyShowIfAssigned,onlyShowItemIfOwned,ownedByDefault},"prices":[{"currency_code","price"}]}],"bundles":[BundleItem]}` | C |
| `AddUserVirtualCurrency` | `PUT {pd}/inventory/{gc}/addcurrency` | `{"amount":int,"currency_code":"…"}` | any object | C |
| `UseVirtualCurrency` | `PUT {pd}/inventory/{gc}/usecurrency` | same | any object | C |
| `GrantUserItem` | `PUT {pd}/inventory/{gc}/player` | `{"allow_duplicate":bool,"expires_on":str,"inventory_item_name":str,"options":str,"uses_remaining":int}` (note: `allow_duplicate` is singular here) | any object | C |
| `PurchaseItem` | `PUT {pd}/inventory/{gc}/item/purchase` | `{"currency_code","inventory_item_name"}` | `{"success":bool,"message":str}` | C |
| `PurchaseBundle` | `PUT {pd}/inventory/{gc}/bundle/purchase` | `{"currency_code","bundle_name"}` | same | C |
| `getTimeSyncV1` | `GET {pd}/time` | – | a JSON **string**, e.g. `"2026-10-10T12:00:00Z"` (deserialised as `string`) | C |
| `SendOtherPlayerData` (end of match, master client reports the **opponent's** deltas) | `PUT {pd}/{gc}/match/processresult` | `{"OtherPlayerId":"…","UserData":{…"Data"…},"VirtualCurrencyDeltas":{"BP":n,…},"AchievementDeltas":[{"achievement_code","achievement_value"}]}` | any object | C keys/URL; I nesting |
| `CreateMatchmakingTicket` | `POST {mm}/matchmaking/ignis/tickets` | `{"game_version":"2.1","match_profile":"Ignis_Ranked"}`. Queue `GlobalRatingPlay` maps to `Ignis_Ranked`; any other queue maps to `Ignis_Tournament`. | `CustomMatchmakingTicketResponse` (B.2) → PlayFab `TicketId = id` | C |
| `GetMatchmakingTicket` (polled) | `GET {mm}/matchmaking/tickets/{ticketId}` | – | `CustomMatchmakingTicketResponse`. PlayFab `MatchId = extensions.match_id`, `Status = status` (verbatim) | C |
| `CancelMatchmakingTicket` | `DELETE {mm}/matchmaking/tickets/{ticketId}` (SDK `HttpMatchmakingClient.DeleteTicket`) | `{"ticket_id":"…"}` | `{"deleted":true}` | C; I: may arrive **without** Authorization, because it goes through the adapter's plain `JsonParsingHttpClient` |
| `GetMatch` | `GET {pd}/ignis/matchmakingprofile/target?player_id=<opponentId>` | – | the opponent's stored `PLAYER_MATCHMAKING_PROFILE` (`JsonObject`) | C |
| `ReportPlayer` | none. Logs "Doing nothing, reporting is turned off." | – | – | C |

### B.2 Matchmaking contract (adapter)
1. Before the ticket: the client writes `PUT {pd}/playerdata/{gc}/PLAYER_MATCHMAKING_PROFILE` with `{"STATISTICS":<achievement summary>,"USERDATA":<all user data>}`. **C**
2. `POST` ticket. The body has **no** player list, region or skill. A server matchmaker must pair tickets by `match_profile` + `game_version`. It can read skill from the stored profile (`STATISTICS.ELO_RATING` / `LEAGUE_POINTS_SEASON`) (I).
3. Ticket response (`CustomMatchmakingTicketResponse`, auto-props):
```json
{"id":"<ticketId>","status":"Matched","create_time":"…","expiration_time":null,
 "assignment":{"connection":"<anything>","teams":[{"id":"team1","playerids":["<me>"]},{"id":"team2","playerids":["<opponent>"]}]},
 "extensions":{"match_id":"<matchId>"}}
```
   - `RatingMatchmakingHandler` acts only on `status == "Matched"` (then uses `match_id`) and `status == "Canceled"`. Anything else means keep polling. **C**
   - `ValidateTicketData` / `GetMatch` require **exactly 2 teams with exactly 1 player each**, and the caller's `userId` must be in one of them. The errors are "Not all teams contain exactly 1 player", "There are {0} teams … instead of 2" and "Current user is not in any of the teams". **C**
4. `GetMatch` picks the other team's id and fetches their profile (B.1). It then builds PlayFab `GetMatchResult.Members`. Photon room and region selection then proceed as in PlayFab mode (I).

### B.3 Data the server must seed (title data `title_data` keys referenced by the adapter) **C**
`LEAGUE_POINTS_SETTINGS, LEAGUE_TIER_TRESHOLDS, LEAGUE_POINTS_SEASON_SETTINGS, MATCHMAKING_SETTINGS, RETENTION_BOT_SETTINGS, SHOOTOUT_DUELS_SETTINGS, TOOL_MASTERY_MISSIONS, TOOL_ATTACHMENT_SETTINGS, MISSION_SEASONS_SETTINGS, MISSION_SEASONS_TEMPLATE_SETTINGS, STORY_EVENT_SETTINGS, TOURNAMENT_SETTINGS, GAME_LOG_UPLOAD_SETTINGS, PING_VALUE_SETTINGS, NETWORK_DIAGNOSTICS_SETTINGS, BOWSER_SETTINGS, DUEL_RG_PICO_RTC, OZO_RG_PICO_RTC, OZO_OFFLINE`, plus the reward constants `EXPERIENCE_POINTS_FOR_*`, `FREEMIUM_FOR_*`, `PREMIUM_FOR_LEVEL_UP` and `FREEMIUM_FOR_LEVEL_UP`.
User-data keys written: `PLAYER_MATCHMAKING_PROFILE, PLAYER_MATCHMAKING_SETTINGS, REWARDS, ASSIGNED_ITEMS, DECKS, STORY_EVENT_DATA, TOOL_MASTERY, OWNED_TOOL_ATTACHMENTS, SELECTED_TOOL_ATTACHMENTS, TOOL_MASTERY_UNLOCKED_TOOLS, COMPLETED_MISSION_SEASONS, MISSION_SEASON_<id>, PROCESSED_EXPERIENCE_AWARDS, TOURNAMENT_TICKETS, USER_MESSAGES`.
Achievement/stat codes: `ROUNDS_WON, RESETTABLE_ROUNDS_WON, ELO_RATING, EXPERIENCE, RESETTABLE_EXPERIENCE, LEAGUE_POINTS_TOTAL, LEAGUE_POINTS_SHADOW, LEAGUE_POINTS_SEASON, LEAGUE_TIER, LOSING_STREAK, TOURNAMENT_GAMES_WON, BOT_LEAGUE_POINTS, TOURNAMENT_PVP_MATCHES_WON_<id>, TOURNAMENT_PVP_MATCHES_LOST_<id>`. The server must **sum deltas** per code within the requested date window.
CloudScript names emulated client-side: `awardExperienceV1, buyTournamentTicketV1, claimMissionSeasonRewardV1, claimRewardV1, claimToolAttachmentsV1, getApiBlastonTokenV1, getBotMatchRewardPredictionsV1, getCurrentMissionSeasonV1, getCurrentStoryV1, getDecksV1, getInventoryV2, getLeaguePointsSeasonV1, getMatchRewardPredictionsV1, getMatchmakingSettingsV1, getPlayerInfoV1, getPlayerSettingsV1, getTimeSyncV1, getToolAttachmentsV1, getToolMasteryMissionProgressV1, getTournamentInfoV1, getUserMessagesV1, getUserTokenV1, nonMasterReportGameV1, reportBotGameEndV1, reportGameEndV1, reportSigningFingerprintV1 (stub), setMatchmakingSettingsV1, setSelectedToolAttachmentsV1, setToolMasteryTrackingV1, storeDeckV1, updateCurrentStoryV1, updateMissionProgressV1, updateToolMasteryMissionProgressV1, upgradeMissionSeasonRewardV1`. The adapter does *not* handle `updateOculusPushNotificationTokenV1` (seen live); it logs "ExecuteCloudScript function unhandled".

---

## C. Fidelity SDK services (library; no Blaston callers except where noted)

All paths hang off `{base}` (`https://playerdata.api.rginfra.dev`). Auth is Bearer through `AuthenticatedHttpClient` unless noted. A "Resp" of `SOR` = `SaveOperationResult`.

### C.1 AchievementService
| Call | Method + path | Body | Resp | |
|---|---|---|---|---|
| Get | `GET /playerdata/achievement/{gc}?achievement_code=&aggregation_method=Sum\|Max\|Latest&end_date=<s>&start_date=<s>` | – | `{"achievement_code","achievement_value"}` | C |
| GetSummary | `GET /playerdata/achievement/{gc}/summary?end_date=<s>&start_date=<s>` | – | `{"achievements":[{achievement_code,achievement_value}]}` | C |
| Set | `PUT /playerdata/achievement/{gc}` | `{"achievement_code","achievement_value"}` | SOR | C |
| GetLeaderboard | `GET /playerdata/achievement/{gc}/leaderboard?achievement_code=&aggregation_method=&end_date=&limit=&minimum_entries=&start_date=` | – | `{"leaders":[{"achievement_count":int,"achievement_value":float,"display_name","player_id","rank":int}]}` | C |
| GetPlacement | `…/{gc}/placement?` (same query) | – | one leader entry | C |

### C.2 LeaderboardService (used by the adapter)
`GetSeasons`: `GET /playerdata/{gc}/seasons` → `GetSeasonsResponse`. It caches start/end per `season_id`. `GetLeaderboard(seasonId, …)`: `GET /playerdata/achievement/{gc}/leaderboard?achievement_code=&aggregation_method=&start_date=<o>&end_date=<o>&limit=&minimum_entries=` → `{"leaders":[{player_id,display_name,rank,achievement_value}]}`. `GetPlayerPlacement`: `…/placement?…&limit=1&minimum_entries=` → one item. An unknown season throws "No prior knowledge of season …". **C**

### C.3 BanService
`PUT /playerdata/ban/{gc}/list`, body `{"feature":"All|CasualMatchmaking|RankedMatchmaking|Voice|Party"}` (`[JsonRequired]` private field; string enum **I**). Resp `{"bans":[{"player_id","game_code","feature","banned_on","ban_reason","ban_expires"}],"time":"<date>"}`. All entry fields are `[JsonRequired]`, so missing fields throw. The client also writes `Application.dataPath/bans.json`. **C**

### C.4 BlockingService (raw `IHttpClient`)
`PUT /playerdata/social/blocked/{gc}/add/{playerId}` body `{}`. `DELETE /playerdata/social/blocked/{gc}/remove/{playerId}` body `{}`. The response string is ignored. **C**

### C.5 DisplayNameService
`GET /playerdata/displayname/{gc}` → `{"PlayerId","GameCode","DisplayName","CreatedOn","OnlineStatus","OnlineStatusUpdatedOn"}`. Both `GetDisplayName` (returns DisplayName) and `GetPlayerProfile` use it. `PUT` on the same path with `{"display_name":"…"}` → SOR. `message=="DisplayNameUnavailable"` → `DisplayNameServiceException(NameNotAvailable)`. **C**

### C.6 FriendsListService
| Call | Method + path | Body | Resp | |
|---|---|---|---|---|
| GetFriendsList(timeout) | `GET /playerdata/social/friends/{gc}?online_timeout_seconds=N` | – | `{"friends":[FriendResponse]}` | C |
| GetFriendsList(keys) | `PUT /playerdata/social/friends/{gc}/with_keys` | `{"playerdata_keys":[…]}` | same | C |
| GetFriendRequests | `GET /playerdata/social/awaiting/{gc}` | – | same | C |
| GetFriendRequests(keys) | `PUT /playerdata/social/awaiting_with_keys/{gc}` | `{"playerdata_keys":[…]}` | same | C |
| FindUsersByDisplayName | `GET /playerdata/social/users/{gc}?display_name=X&exact_match=true\|false` | – | `{"Result":[{"PlayerId","DisplayName","playerdata_entries":{}}]}` | C |
| FindUsersByDisplayName(keys) | `PUT /playerdata/social/users_with_keys/{gc}` | `{"display_name","exact_match","playerdata_keys"}` | **bare array** `[{"player_id","display_name","playerdata_entries":{}}]` | C |
| RequestAddFriend / AcceptFriendRequest / RejectFriendRequest / RemoveFriend | `PUT /playerdata/social/friends/{gc}/{request\|accept\|reject\|remove}?friend_player_id=ID` | `""` | SOR | C |

`FriendResponse` = `{"player_id","display_name","friend_request_status":"Pending|Accepted|Blocked","online_status":"Offline|InMatch|Online","online_status_updated_on","friend_request_updated_on","playerdata_entries":{str:str}}` (all strings). **C**

### C.7 HealthService
`GET /playerdata/ping` (any body; latency measured). `GET /playerdata/time` → body trimmed of a char (I: `"`) and parsed with `DateTime.TryParse`. "Empty result" counts as a failure. **C**

### C.8 InventoryService (also used through `MultiplatformIAP.MercuryBackendService`, adapter-only)
| Call | Method + path | Body | Resp | |
|---|---|---|---|---|
| GetUserInventory | `GET /playerdata/inventory/{gc}` | – | `{"Items":[InventoryItemResponse]}` (PascalCase; ids are **strings** here) | C |
| GetCatalog | `GET /playerdata/inventory/{gc}/catalog?bundle_class=&item_class=` | – | `{"bundles":[BundleItem],"items":[InventoryItem]}` | C |
| GetCurrency | `GET /playerdata/inventory/{gc}/currency?currency_code=` | – | bare int | C |
| GetBundlePrice | `GET /playerdata/inventory/bundle/price?asset_name=&currency_code=` (**no gc**) | – | bare int | C |
| AddCurrency / UseCurrency | `PUT /playerdata/inventory/{gc}/addcurrency` / `usecurrency` | `{"amount","currency_code"}` | SOR | C |
| PurchaseItem | `PUT /playerdata/inventory/{gc}/item/purchase` | `{"currency_code","inventory_item_name"}` | SOR | C |
| PurchaseBundle | `PUT /playerdata/inventory/{gc}/bundle/purchase` | `{"bundle_name","currency_code"}` | SOR | C |
| AddItem | `PUT /playerdata/inventory/{gc}/player` | `{"allow_duplicates","expires_on","inventory_item_name","uses_remaining","options"}` | `{"message","new_id":int?,"success"}` | C |
| AddItemUses | `PUT /playerdata/inventory/item/add_uses` (no gc) | `{"added_uses","player_inventory_id"}` | SOR | C |
| ConsumeItemUses | `PUT /playerdata/inventory/item/consume_uses` | `{"consumed_uses","player_inventory_id","remove_if_consumed"}` | SOR | C |
| RemoveItem | `DELETE /playerdata/inventory/item/remove` | `{"player_inventory_id"}` | SOR | C |

`InventoryItem` = `{consumable_count?,consumable_seconds?,description,id,item_class,max_per_player?,max_per_title?,name,tradeable,options,prices:[{currency_code,price}]}`. `BundleItem` = `{bundle_class,bundle_id,bundle_name,currencies:[{amount,currency_code}],default_consumable_days,items:[{inventory_item_id,quantity}],prices:[{currency_code,price}],options}`. **C**

### C.9 IAPShopService (Facade)
`PUT /playerdata/{gc}/inventory/ensure` (`""`), `/inventory/tier_skip` (`""`), `/inventory/premium_track` and `/inventory/premium_track_deluxe` (`{"battle_pass_name"}`) → SOR. On error the client parses `ErrorMessage{"error"}` (values probably `BattlePassError` names: AlreadyPurchased, AlreadyMaxLevel, MultiplePassesActive, NoPassActive, NotFound **I**). **C**

### C.10 MatchService
`PUT /playerdata/match/record` (no gc), body `NewMatch` = `{"game_code":"ignis","game_server_name","is_allocated","is_public","match_identifier","match_profile":"Private","node_name","teams":[{"player_ids":[…],"team"}],"game_version":null,"regions":null}` → SOR. `Update` = **PATCH** on the same URL and body. `SendResult` = `PUT /playerdata/match/{gc}/result`, body `{"match_id","max_team_size","match_profile","match_started","match_ended","win_type":"Points|Elimination|Achievement|Forfeit|Leave|Unknown","team_results":[{"team_label","score","is_winner","players":[{"player_id","player_display_name","is_leave_offender","player_achievements":[{achievement_code,achievement_value}]}],"team_achievements":[…]}]}` → SOR. **C**

### C.11 Matchmaking: HttpMatchmakingClient / MercuryMatchMakingService (base = `{mm}`)
| Call | Method + path | Body | Resp | |
|---|---|---|---|---|
| Create | `POST /matchmaking/{gc}/tickets` (or `/matchmaking/tickets` if gc empty) | `{"match_profile","game_version","region","player_identities":[…]}` | `{"id","assignment":{"connection","teams":[{"id","playerids":[]}]},"extensions":{"match_id","host_id"}}` | C |
| Get | `GET /matchmaking/tickets/{id}` | – | same | C |
| Delete | `DELETE /matchmaking/tickets/{id}` | `{"ticket_id"}` | `{"deleted":bool}` | C |

`MercuryMatchMakingService.GetTicket` sets status **Matched iff `assignment.connection` is non-null**, else Waiting. `matchId`/`hostId` come from `extensions`. **C** (The adapter instead passes the raw `status` string through, see B.2.)

### C.12 OnlineStatusService
`PUT /playerdata/social/onlinestatus/{gc}` body `{"status":"Offline|InMatch|Online"}` → SOR. **C**

### C.13 PartyService
| Call | Method + path | Body | Resp | |
|---|---|---|---|---|
| CreateParty | `PUT /playerdata/social/party/{gc}` | `{"party_code","party_name","network_id","open_party","generate_party_code"}` | `PartyDetails` | C |
| GetParty | `GET /playerdata/social/party/{gc}?party_code=X` | – | `PartyDetails` | C |
| GetPlayerParties / GetPendingPartyInvitations / GetLocalPartyInvitations | `GET /playerdata/social/party/{gc}/list` | – | `{"parties":[{"party_code","party_name","created_on","network_id","invited_on","joined_on","is_host","invitation_status"}]}`, filtered client-side (I) | C |
| JoinParty / AcceptPartyInvite | `PUT …/{gc}/join` | `{"party_code"}` | SOR | C |
| RejectPartyInvite | `PUT …/{gc}/reject` | `{"party_code"}` | SOR | C |
| InviteToParty / RemoveFromParty | `PUT …/{gc}/invite` / `/remove` | `{"party_code","invited_player_id"}` | SOR | C |
| DeleteParty | `DELETE …/{gc}?party_code=X` | – | SOR | C |
| LeaveParties | `DELETE …/{gc}/leave_all_parties` | – | SOR | C |

`PartyDetails` = `{"party_code","created_on","network_id","party_name","players":[{"player_id","display_name","is_host","party_invitation_status":"Pending|Accepted"}]}`. **C**

### C.14 PlayerDataService
`GET /playerdata/playerdata/{gc}/{key}` → raw JSON value. `PUT` on the same path with the JSON value → SOR. `DELETE /playerdata/playerdata/{gc}` (all) and `/{gc}/{key}` → SOR. `GET /playerdata/playerdata/{gc}/keys` → `["k1",…]`. `GetExportableKeys`: `PUT /playerdata/profile/{gc}/target` (verb **I**; body + callerMethod pattern), body `{"player_id","playerdata_keys":[…],"achievement_keys":[{"achievement_code","aggregation_method","start_date","end_date"}]}` → `{"player_id","game_code","display_name","online_status","online_status_updated_on","created_on","playerdata_entries":{…},"achievement_entries":{…}}`. **C** (except the verb)

### C.15 QuestsService
`GET /playerdata/quests/{gc}/active` → `{"quests":[{"id","quest_code","earliest_completion_time","latest_completion_time","failed_quests_can_be_retried","options","game_specific_reward","tasks":[{"achievement_code","aggregation_method","current_value","target_value","order","options"}]}]}`. `GET …/{gc}/available` → `{"quests":[{"quest_code","options","game_specific_reward","tasks"}]}`. `PUT …/{gc}/start?quest_code=` (`""`) → SOR. `PUT …/{gc}/end?quest_code=` (`""`) → `{"game_specific_reward","is_completed"}`. `PUT …/{gc}/progress?achievement_code=&quest_code=&value=` (`""`) → SOR. `SetTemplates` has no body or strings (not implemented). **C**

### C.16 TitleDataService / TitleDataAdminService
User: `GET /playerdata/titledata/{gc}/{key}` → raw JSON (typed) or string. `PUT` on the same path → **bare int** (typed `Set<T>`) or string (`Set(string)`). Admin: `GET/PUT /playerdata/admin/titledata/{gc}/{key}` (PUT → int). `PUT /playerdata/admin/titledata/{gc}` (Add → int). `PUT /playerdata/admin/titledata/edit/{gc}/{key}` (Edit → int). `DELETE /playerdata/admin/titledata/edit/{gc}/{key}` (→ int). `List` is empty. **C**

---

## D. Realtime channels (SDK; none instantiated by Blaston)

### D.1 SSE transport (`EventSource`, `HttpEventStream`) **C**
- `GET <url>` through `AuthenticatedHttpClient.DoGetAsync` (Bearer). The body is read as a stream. Standard SSE parsing: fields `event`, `data`, `id`, `retry`, lines split on LF, a leading space after `:` stripped, default type `message`.
- Reconnect sends `Last-Event-ID`, with `reconnectionTime` / `maxReconnectionAttempts` from `SSEListenerInit`.
- `ServerSentEventsListener<T>` deserialises **`data` as JSON `T`**. Dispatch uses the payload's `trigger_type`, not the SSE `event` name, so sending plain `data: {...}\n\n` is enough. `trigger_type` is an enum and can be sent as an int or a name (I: names safer).

| Listener | URL | Payload `T` | Dispatch | |
|---|---|---|---|---|
| FriendsSSEListener | `{base}/playerdata/social/friends/{gc}/listen` | `FriendEvent {"friend_player_id","friend_display_name","trigger_type":0..5,"triggered_on","friend_entry":{"player_id","display_name","friend_request_status","friend_request_updated_on","online_status","online_status_updated_on","playerdata_entries"}}` | 0 FriendRequest, 1 FriendRequestAccepted, 2 FriendRequestDeclined, 3 FriendRemoved, 4 OnlineStatusChanged, 5 DisplayNameChanged | C |
| PartySSEListener | `{base}/playerdata/social/party/{gc}/listen` | `PartyEvent {"party_code","trigger_type":0..4,"source_player_id","party_details":PartyDetails,"triggered_on"}` | 0 PartyCreated, 1 PlayerJoined, 2 PlayerLeft, 3 PlayerInvited, 4 PartyDeleted | C |
| PartyBroadcastSSEListener | `{base}/playerdata/social/party/{gc}/listen/{partyCode}` (I: order of the last parts) | `{"source_player_id","triggered_on","message_type","message"}`. `message` may carry `{"player_id","event_type":"PlayerJoined|PlayerLeft"}` (`PartyBroadcastRoomPresenceEvent`) | raw | C fields; no send endpoint found (`PartyBroadCastMessageCommand{message_type,message}` is unused) |

### D.2 WebSocket (`PartyEventSocketListener : SocketListener<PartyEvent,object>`) **C**
- URL `baseUrl + "/playerdata/ws/party/" + gameCode`. The caller must supply a `wss://` base (I).
- Header `Authorization: <authToken>`. Text frames hold JSON `PartyEvent` (same as SSE), max 1 MiB per message.
- Events: PlayerJoined → RemotePlayerJoined, PlayerLeft → RemotePlayerLeft, PartyDeleted, PlayerInvited.
- Reconnect uses `ExponentialBackoffStrategy`. Modes: `TryNextQueue` (poll) or `OnMessageReceivedEvent`. The send queue exists, but nothing sends.

---

## E. Minimum viable server

### E.1 Unpatched 2.3.3 (PlayFab mode), for Mercury only
| Prio | Endpoint | Needed for | Minimal answer |
|---|---|---|---|
| P0 | A1 config selector `…/ignis/<ver>/urls` (+ `adhoc`) | startup (failure looks tolerated, but it is cheap) | static JSON pointing at your hosts |
| P1 | token service `…/oculus/generate-user-token/…` etc. | telemetry tracking id only (not blocking, I) | `{"token":"Bearer x","valid_until":"2099-01-01T00:00:00Z","user_data":{"user_identity":"<id>","display_name":"<n>"},"tracking_id":"<uuid>"}` |
| P2 | A3 `playerdata.resgam.com/playerdata/titledata/ignis/<key>` (+ `auth.resgam.com` token) | A/B remote config | `404` or `{}` |

Login, menu, matchmaking and match all depend on **PlayFab + Photon + api.blaston.com**, not Mercury.

### E.2 If the adapter is enabled by patch (login → menu → matchmaking → match)
| Prio | Endpoint | Must return real data? |
|---|---|---|
| P0 | token service (Bearer-prefixed `token`, non-empty `user_identity`) | **yes** |
| P0 | `GET {pd}/titledata/ignis/title_data` | **yes**: PlayFab-shaped `Data` with the B.3 keys (captured PlayFab title data) |
| P0 | `GET {pd}/ignis/tournament` | `{}` OK |
| P0 | `GET {pd}/playerdata/ignis/user_data` | `{"Data":{}}` for a new player, then persisted KV |
| P0 | `GET {pd}/displayname/ignis` | `{"DisplayName":"…"}` |
| P0 | `PUT {pd}/playerdata/ignis/{key}` | store; `{"success":"true"}` |
| P0 | `GET {base}/playerdata/ignis/seasons` | **yes**: at least one season covering *now* (else stats fail) |
| P0 | `GET {pd}/ignis/achievement/summary?…` / `PUT {pd}/achievement/ignis` | sum-of-deltas store; `{"achievements":[]}` OK initially |
| P0 | `POST {mm}/matchmaking/ignis/tickets`, `GET {mm}/matchmaking/tickets/{id}`, `DELETE …/{id}` | **yes**: pair 2 tickets with the same profile/version → `status:"Matched"`, 2×1 teams, `extensions.match_id` |
| P0 | `GET {pd}/ignis/matchmakingprofile/target?player_id=` | opponent's stored `PLAYER_MATCHMAKING_PROFILE` |
| P1 | `GET {pd}/{gc}/inventory/get_player_currencies`, `GET {pd}/inventory/ignis`, `GET {base}/playerdata/inventory/ignis/catalog` | shop and cosmetics; empty lists OK to reach the menu (I) |
| P1 | `PUT {pd}/inventory/ignis/{addcurrency,usecurrency,player,item/purchase,bundle/purchase}` | rewards and shop; `{}`/`{"success":true}` |
| P1 | `PUT {pd}/ignis/match/processresult` | opponent's post-match deltas (master client); `{}` OK |
| P2 | `GET {pd}/time` | `"<ISO date>"` |
| P2 | `GET {pd}/titledata/ignis/title_news`, LP leaderboard, placement, `PUT {pd}/displayname/ignis` | `{"News":[]}`, `{"leaders":[]}`, `{"success":"true"}` |
| — | Friends, Party, SSE, WS, Quests, Ban, Blocking, OnlineStatus, Match record, IAPShop, Health, TitleDataAdmin | not called by Blaston; skip |

---

## F. Open questions
1. Exact `status` vocabulary of the real Mercury matchmaker. The client only checks `"Matched"` and `"Canceled"`; PlayFab-style `"WaitingForMatch"` is a safe "waiting" value (I).
2. Whether `user_data` and `title_data` are reserved "return everything in PlayFab format" keys, or real stored keys (I).
3. Value encoding of `SavePlayerDataEntry`: the body is the client's serialized JSON text. Whether `GET user_data` should return it verbatim as `Value`, or unwrap JSON strings, is unknown. Returning the exact text the client PUT is the safest bet (I).
4. The adapter's own `JsonParsingHttpClient` backing client is unknown (its ctor has no caller). `DELETE` ticket may come without auth.
5. `SendOtherPlayerData` body nesting (`UserData.Data`) and the semantics of `VirtualCurrencyDeltas` are inferred from key literals only.
6. The real live hosts (`playerdata.api.rginfra.dev`) could only be observed through the config JSON. No Mercury request or response bodies were captured. **Capture `title_data` from PlayFab now**: it is the only irreplaceable input for E.2.
