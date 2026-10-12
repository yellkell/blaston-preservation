# Blaston and PlayFab (title `B0549`)

This document comes from static analysis of the PC build (x64 ISIL in `dump/`) and the Quest build (ARM64 in `dump-quest/`), version 2.3.3.302372, plus the 2026-10-09 Quest logcat (`capture/quest/`).

Each claim is tagged:
- **CONFIRMED**: read directly from string literals, MethodInfo/type annotations, or field writes.
- **INFERRED**: an educated guess. The reason is given.

---

## 0. Headline findings

1. **The live build always talks to PlayFab.** **CONFIRMED.** `ServerClientAdapterFactory.CreateServerClientAdapter()` always creates `PlayFabServerClientAdapter`. All PlayFab traffic goes through the interface `RGCommon.ServerClient.IServerClientAPI` (24 methods, listed in section 2).
2. **There is a second backend adapter that isn't used, and it is the most useful find here.** `RGCommon.ServerClient.MercuryServerClientAdapter` implements the same `IServerClientAPI` on top of Resolution Games' "Mercury" backend. Its `ExecuteCloudScript()` is a big `switch` on the CloudScript function name, and it re-implements 34 of the 45 CloudScript functions **client-side**. The logic covers ELO, league points, XP and levels, rewards, missions, tool mastery, story, tournaments and decks. It also reads the same title-data, user-data and statistic keys as the real CloudScript, which it was clearly ported from.
   - **CONFIRMED** that the code exists; it lives in `dump/isil/IsilDump/Assembly-CSharp/RGCommon/ServerClient/MercuryServerClientAdapter*.annotated.txt` (460 files).
   - **INFERRED** that its key names and logic match the live JS CloudScript. Every key it uses is also a const in the class, the function names and argument names are identical, and the result shapes match the DTOs the PlayFab path parses.
   - ⇒ **This is the best reference available for rewriting the CloudScript.** Decompiling these method bodies is the next step.
3. **No receipt-validation APIs are used.** **CONFIRMED.** `ValidateGooglePlayPurchase`, `ValidateIOSReceipt` and the others have no callers.
   - Quest IAP goes through the CloudScript function **`buyCoinsV2`**.
   - Steam IAP goes through PlayFab's native `StartPurchase` → `PayForPurchase("Steam")` → `ConfirmPurchase` flow. See section 4.
4. **The client never writes statistics.** **CONFIRMED.** It never calls `UpdatePlayerStatistics`; every statistic change happens server-side in CloudScript (`reportGameEndV1` and similar).
5. **Login.** `LoginWithCustomID` (Quest) and `LoginWithSteam` (PC) both send `CreateAccount=true` and an `InfoRequestParameters` block that asks for statistics, title data, account info, user data, inventory and virtual currency, with **no key filters**. **CONFIRMED.**
   - So **all title data and all user data are sent to every client at login**. Any logged-in client can therefore dump the complete client-visible title data. See section 5.
6. **`GetPhotonAuthenticationToken` is never called by game code.** **CONFIRMED.** It exists only in the PlayFab SDK, has no caller outside `PlayFab.dll`, and does not appear in the logcat. Photon `AuthValues` are built in `EntryPoint`.
7. **An internal debug tool in the client embeds a credential for RG's stage title (`C6A22`).** Its location and value are deliberately not documented here. It should not be used, and it is better reported to Resolution Games privately.
   - It calls the Admin APIs `SetTitleData` (key `TOURNAMENT_SETTINGS`) and `IncrementPlayerStatisticVersion` (stats `TOURNAMENT_PVP_MATCHES_WON_3LossYouAreOut` and `TOURNAMENT_PVP_MATCHES_LOST_3LossYouAreOut`).
   - Correction to `FINDINGS.md`: `RG.IgnisBowser.PlayFab.PlayFabReferenceData` has `releaseEnvironmentId = "B0549"` and `stageEnvironmentId = "C6A22"`. **CONFIRMED.**
8. **Production title-id check.** `Ignis.BarEntranceHandler.GoToBar()` compares the current title with the literal `"B0549"` (near the `IsProductionKey` literal). On a new title id, the bar/Arcade may think it is running in a non-production environment.
   - **CONFIRMED** that the literal is there. **INFERRED** what effect it has.

---

## 1. CloudScript functions (legacy `/Client/ExecuteCloudScript`)

### How the client calls them
- **Queued calls:** `RGCommon.PlayFab.PlayFabCloudScriptInvocationHandler` takes `CloudScriptInvocationRequest(functionName, functionParameter, retryCount=5, retryTimeout=30, shouldCacheResponse=true, useCachedResultIfAvailable=false, verifyType, curfew)` objects. It sends them **one at a time** through `IServerClientAPI.ExecuteCloudScript`. **CONFIRMED.**
- **Direct calls:** some facades call `IServerClientAPI.ExecuteCloudScript` themselves. The "Facade (direct)" column below marks these. They do not appear as "invoking X" in the log. **CONFIRMED.**
- **Arguments:** the request sets `FunctionName`, `FunctionParameter` (a C# anonymous type serialized by PlayFab SimpleJson, so the property names below are the exact JSON keys), and `GeneratePlayStreamEvent=true`. **CONFIRMED** for the first two. **INFERRED** for `GeneratePlayStreamEvent`, because `Nullable<bool>(true)` is built next to it.
- **Response handling:** `PlayFabUtil.ExtractJsonResponse(result)` takes `FunctionResult.ToString()`, replaces `\"`→`"`, `"[`→`[` and `]"`→`]`, then most callers run `UnityEngine.JsonUtility.FromJson<T>`. **CONFIRMED.**
  - ⇒ The server should return a plain JSON **object**. JsonUtility needs field names to match exactly, and it can't read top-level arrays or dictionaries.
  - A few callers instead read `FunctionResult` as a `PlayFab.Json.JsonObject` and look up keys (`status`, `ifIWin`, …).
- **Response cache:** when `shouldCacheResponse` is true, responses are kept in `PlayerPrefs` under the key `PlayFabCloudScriptCache_` + playerId + function + sanitised parameter (regex `[{,}, ,=]`→`_`), with the player id stored under `PlayFabCloudScriptCachePlayerId`. **CONFIRMED.**
  - ⇒ **Capture tip (INFERRED):** a PC install that has been played keeps the last response of every cached function in the registry, under `HKCU\Software\Resolution Games\Blaston`.
- **Field casing:** `toolName`, `toolAttachment` and `deckName` are sent as `Enum.ToString().ToLower()`, e.g. `"smg"`, `"default"`, `"classic"`. **CONFIRMED.**

### Function table

"Mercury ref" means the function is re-implemented in `MercuryServerClientAdapter`, so a reference implementation exists. All function names, callers and argument names are **CONFIRMED**. Result shapes are **CONFIRMED** where a DTO or literal key is given.

| Function | Caller (class::method) | Args (JSON) | Result the client expects | Mercury ref |
|---|---|---|---|---|
| `getInventoryV2` | `Ignis.OwnershipHandler::RequestInventoryUpdate` (queued) | none | `GetInventoryResponse {items:[InventoryItem{itemId,itemClass,isLocked,isOwned,isVisible,price,currencyCode,requiredLevel,isAvailableForUnlocking}], virtualCurrencies:{BP:int,FR:int}}` | yes |
| `assignItemV1` (debug) | `OwnershipHandler::AssignItemDebug` | `{itemId}` | ignored | no |
| `getDecksV1` | `RG.Ignis.PlayFab.PlayFabDeckHandler::IssueGetRequest` | none | `GetDecksResponse {decks:[{deckName, tools:[{toolName,toolAttachment}]}]}`; `deckName` is a GameplayRules name (`classic`/`shootout`/`winterclassic`/`scrappershootout`) | yes |
| `storeDeckV1` | `PlayFabDeckHandler::IssueStoreRequestIfThereAreLocalModifications` | `{deckName:"classic", tools:[{toolName:"smg",toolAttachment:"default"},…]}` | ignored; a `getDecksV1` reload follows | yes |
| `getToolAttachmentsV1` | `PlayFabToolAttachmentHandler::MakeGetAttachmentsRequest` | none | `GetAttachmentsResponse {selectedAttachments:[Tool], ownedAttachments:[Tool]}`, `Tool={toolName,toolAttachment,claimed}` | yes |
| `setSelectedToolAttachmentsV1` | `PlayFabToolAttachmentHandler::MakeSetAttachmentsRequest` | `{selectedAttachments:[{toolName,toolAttachment}]}` (lower-case strings) | ignored | yes |
| `claimToolAttachmentsV1` | `PlayFabToolAttachmentHandler::CheckClaimAttachmentQueueAndSendRequests` | `{attachmentsToClaim: ToolSet[]}`. `ToolSet{toolName,toolAttachment}` are C# enums. **INFERRED:** they go out as numbers (SimpleJson `SerializeEnum`→`Convert.ToDouble`), whereas the Mercury port reads strings. Verify against live traffic. | `ClaimAttachmentsResponse {ownedAttachments:[Tool]}` | yes |
| `getToolMasteryMissionProgressV1` | `PlayFabToolMasteryHandler::SendGetMissionStatusRequest` | none | `MasteryMissionProgress {missions:[{missionId,progress,amountToComplete,active,toolName,toolAttachment,qualifier,complete}], masteryUpdated, toolsWereUnlocked, attachmentsWereUnlocked}` plus `toolMasteryTracking:{toolName,toolAttachment}` in the same JSON (it is also parsed as `ToolMasteryTracking`) | yes |
| `setToolMasteryTrackingV1` | `PlayFabToolMasteryHandler::SendSetToolMasteryRequest` | `{toolName, toolAttachment}` | ignored; a get follows | yes |
| `updateToolMasteryMissionProgressV1` | `PlayFabToolMasteryHandler::SendMissionProgressRequest` | `{toolName, toolAttachment, qualifier, missionId, isDelta:bool, value:int}` | same shape as `getToolMasteryMissionProgressV1` | yes |
| `resetToolMasteryV1` (debug) | `PlayFabToolMasteryHandler::DebugResetToolMastery` | none | ignored | no |
| `getCurrentMissionSeasonV1` | `PlayFabSeasonMissionHandler::LoadCurrentMissionsSeason` | none | `{currentSeason: PlayerMissionsProgress, completedSeasons:[CompletedSeason], unlocksAtLevel:int}`, with `PlayerMissionsProgress {seasonId,startTime,endTime,missions:[{missionId,progress,amountToComplete,active,complete,qualifier,unlockTime}],missionRewards:[PlayerMissionReward]}`, `PlayerMissionReward {rewardId,itemId,premiumReward,freemiumReward,premiumPrice,freemiumPrice,unlocked}`, `CompletedSeason {seasonId,timestamp,rewardClaimed,missionRewards}` | yes |
| `updateMissionProgressV1` | `PlayFabSeasonMissionHandler::SendUpdateRequest` | `{seasonId, missionId, qualifier, isDelta, value}` | `{status:"success", season, completedSeasons}` | yes |
| `upgradeMissionSeasonRewardV1` | `PlayFabSeasonMissionHandler::SendUpgradeRequest` | `{seasonId, rewardId}` | `{status:"success", season, completedSeasons, userVirtualCurrencies:{BP,FR}}` (error: `"Cannot afford upgrade."`) | yes |
| `claimMissionSeasonRewardV1` | `PlayFabSeasonMissionHandler::SendClaimRewardReqeust` | `{seasonId}` | `{status:"success", season, completedSeasons}` | yes |
| `getLeaguePointsSeasonV1` | `PlayFabLeaguePointsSeasonHandler::CheckIfTimeToSendNewRequest` | none | `{currentSeason, previousSeason}`, each `{seasonName, version, leaderboard:[{displayName,playFabMasterPlayerId,position,value}], nextReset, lastMatchStartTimestamp, firstMatchStartTimestamp, myPosition:[…]}` | yes |
| `getPlayerInfoV1` | (a) `PlayFabExperienceFacade::ReqeustExperience` (direct); (b) `PlayFabPlayerIdentitiesHandler::Tick` (queued) | (a) `{}`; (b) `{playerEntityId}` | `PlayerInfoFromPlayFab {level,maxLevel,totalExp,currentLevelExp,currentLevelSpan,leaguePoints,leagueTier,rewards:[RewardFromPlayFab],displayName,masterPlayerAccountId}`, with `RewardFromPlayFab {claimed, rewardId, rewardType, time, data:{newLevel,freemium,premium,exp,position,season,points}}` (all strings) | yes |
| `awardExperienceV1` | `PlayFabExperienceFacade::AwardExperience` (direct) | `{reason, amountKey, rewardType}`; e.g. a tool purchase sends reason `purchase_tool_<TOOL>`, and **INFERRED** amountKey = title-data key `EXPERIENCE_POINTS_FOR_BUYING_TOOL` | `{status:"processed"}` or `{status:"already_processed"}` (deduplicated by reason, user data `PROCESSED_EXPERIENCE_AWARDS`) | yes |
| `claimRewardV1` | `PlayFabExperienceFacade::ClaimReward` (direct) | `{rewardId}` | `{status:"processed"/"already_processed"}` | yes |
| `getMatchRewardPredictionsV1` | `PlayFabMatchRewardPredictionFacade::CreateRequest` (direct) | `{opponentEntityId, randomSeed, matchmakingQueue}` | `{ifIWin:{winnerLeaguePoints,loserLeaguePoints,winnerExp,loserExp,winnerFreemium,loserFreemium,winnerPremium,loserPremium}, ifILose:{…}}` | yes |
| `getBotMatchRewardPredictionsV1` | same facade | `{botId, randomSeed, matchmakingQueue}` | same as above | yes |
| `reportGameEndV1` | `Ignis.PlayFabMatchReportFacade::ReportMatchResult` (direct), when `EndOfMatchReport.iAmMaster == true` | `{matchId, opponentEntityId, myScore:float, opponentScore:float, matchmakingQueue, randomSeed, endReason:"<MatchEndReason>"}` | `{status:"reported"}` | yes |
| `nonMasterReportGameV1` | same method, when `iAmMaster == false` | same args | `{status:"reported"}` | yes |
| `reportBotGameEndV1` | `PlayFabMatchReportFacade::ReportBotMatchResult` | `{matchId, botId, myScore, opponentScore, randomSeed, matchRewardFactor:float, endReason}` | `{status:"reported"}` | yes |
| `resetLosingStreakV1` | `Ignis.PlayFabMatchReportingHandler::Tick` (queued) | none | ignored | no |
| `getMatchmakingSettingsV1` | `PlayFabMatchmakingSettingsFacade::GetSettings` (direct, after `GetQueueStatistics`) | `{queueSettings: "<JsonUtility.ToJson(GetQueueStatisticsResult)>"}` (**INFERRED:** it is the queue-stats JSON string) | `RatingMatchmakerSettingsData {queueSettings:{timeToWaitUntilBot,giveUpAfterSeconds,createTicketTimeout,cancelTimeout,rematchBlockTime,minimalTimeBetweenReentry,trainingModeUnlockAtLeagueTier,botOnOffUnlockAtLeagueTier,botRewardsOnOffUnlockAtLeagueTier,acceptedRegionPing}, retentionBotSettings:{retentionBotProbabilitySlopeCoefficient,retentionBotLeaguePointReductionPercentage}, playerMatchmakingSettings:{…}, shootoutDuelSettings:{shootoutDuelsEnabled,winterClassicDuelsEnabled,scrapperShootoutDuelsEnabled}}` | yes |
| `setMatchmakingSettingsV1` | `PlayFabMatchmakingSettingsFacade::SetMatchmakingSettings` (direct) | `{settings:{botRewardsActive,skipBots,trainingMode,trainingDifficulty,alwaysQueue}}` | Mercury returns `{"status":"processed"}`; the client only logs it | yes |
| `getTournamentInfoV1` | `PlayFabTournamentEventFacade::GetTournamentInfo` (direct) | none | `ListOfTournaments {tournaments:[{settings:{tournamentId,visibleFromTime,visibleToTime,startTime,endTime,stopAcceptingReportsTime,leagueTierLimit,lossLimit,matchmakingQueue,entryFeeBlasts,winMatchRewardBlasts,gameplayRules}, leaderboard:[{displayName,masterPlayerId,position,value}], player:{wins,losses,inTournament}}]}` | yes |
| `buyTournamentTicketV1` | `PlayFabTournamentEventFacade::BuyTournamentEntry` (direct) | `{tournamentId}` | any string containing `success` (Mercury: `{status:"success"}`); spends BP, user data `TOURNAMENT_TICKETS` | yes |
| `getTimeSyncV1` | `PlayFabServerTimeSyncFacade::GetTimeSync` (direct) | `{clientTime:"<ISO-8601 'o'>"}` | `PlayFabTimeSyncData {serverTime:string, offsetInSeconds:int}` | yes |
| `getUserTokenV1` | `PlayFabApiTokenFacade::GetApiToken` (direct) | none | `{token, valid_until}` | yes |
| `getApiBlastonTokenV1` | `RG.IgnisBowser.BlastonApiTokenHandler::MakeNewRequest` (queued, not cached) | none | `{token, valid_until}`, the bearer token for `https://api.blaston.com/` (knockout tournaments, tokens, rooms) | yes |
| `getCurrentStoryV1` | `IgnisBowser.Story.PlayFabStoryHandler::RequestCurrentStoryEvent` | none | `GetCurrentStoryResponse {currentObjective:{objectiveId,amountToComplete,rewardWhenObjectiveComplete:{grantAccessToItems[],freemiumReward,premiumReward},completed,sortOrder,progress,active}, currentStageId, currentAct:{actId, stages:[{stageId, objectives:[…]}]}, actId}` | yes |
| `updateCurrentStoryV1` | `PlayFabStoryHandler::RequestStoryEventUpdate` | `{objectiveId, progressValue:int, isDeltaUpdate:bool}` | same as `getCurrentStoryV1` | yes |
| `deleteAllStoryProgressV1` (debug) | `Ignis.StoryProgressHandler::DebugClearStoryProgress` | none | ignored | no |
| `getPlayerSettingsV1` | `PlayFabUserSettingsHandler::RequestSettings` | none | `PlayFabPlayerSettings {bowserSettings:{allowedToEnterBar,allowedToEnterAlley,banned}, gameLogUploadSettings:{upload,batchSize,secondsToRecordAfterEndOfMatch}, networkDiagnosticsSettings:{pingWarningThresholdMs,numberOfSecondsBeforeHighPingIsConsideredBad}, adsSettings:{platformAdsSettings:[{platform,adsEnabled}]}, pingSettings:{pingLimits:[int],pingInterval}}` | yes |
| `getUserMessagesV1` | `PlayFabUserMessageHandler::Tick` | none | `{messages:[{messageId, messageText}]}`, shown as an OK dialog (user data `USER_MESSAGES`) | yes |
| `ackUserMessagesV1` | `PlayFabUserMessageHandler::Tick` | `{messageId}` | ignored | no |
| `reportSigningFingerprintV1` | `CertificateFingerprintTrackingHandler::Tick` (direct; logs "Reported fingerprint to PlayFab") | `{fingerprint}`, the APK signing-cert fingerprint | ignored. Mercury: "requires implementation!" **INFERRED:** anti-tamper telemetry only; a revival can return `{}`. | stub |
| `updateOculusPushNotificationTokenV1` | `Ignis.PlayFabPushNotificationInfoHandler::Tick` | `{token, recipientId}` | ignored; can be a no-op | no |
| `triggerPushNotificationV1` (debug) | `PlayFabPushNotificationInfoHandler::SendDebugNotifcation` | `{notificationId}` | ignored | no |
| `triggerRetentionPushNotificationV1` (debug) | `…::SendDebugRetentionNotifcation` | `{}` | ignored | no |
| `generateDisplayNameV1` | `RGCommon.PlayFab.PlayFabLoginFacade::SetRandomDisplayName` (direct) | `{}` | a generated name. The client then calls `UpdateUserTitleDisplayName` with it. **INFERRED:** `FunctionResult` is the plain name string. | no |
| `buyCoinsV2` | `Fidelity.MultiplatformIAP.PlayfabBackendService::GrantBundle` (Quest IAP; name taken from `CurrencyShopSettings.BUY_COINS_FUNCTION`) | `{productId:"Blasts_Pack_N", transactionId:"<Sku>-<GrantTime>"}` | JsonObject `{status:"processed"}` or `{status:"already_processed"}`; anything else triggers a retry after 3 s | no |
| `debugAddCoinsV1` (debug) | `CurrencyShopSettings.DEBUG_GRANT_COINS_FUNCTION` | unknown | unknown | no |

That is 45 functions. Ten are debug-only or no-op candidates: `assignItemV1`, `resetToolMasteryV1`, `deleteAllStoryProgressV1`, `triggerPushNotificationV1`, `triggerRetentionPushNotificationV1`, `debugAddCoinsV1`, `reportSigningFingerprintV1`, `updateOculusPushNotificationTokenV1`, `ackUserMessagesV1` (trivial) and `resetLosingStreakV1`. **CONFIRMED** that they exist. The no-op classification is **INFERRED**.

---

## 2. PlayFab Client and Multiplayer APIs the game calls

All callers are outside `PlayFab.dll` (`dump/xrefs/call_xrefs.tsv` plus request-type construction in ISIL). **CONFIRMED.**

| API | Called from | Notes |
|---|---|---|
| `Client/LoginWithCustomID` | `PlayFabLoginFacade::LoginWithCustomId` | Quest/Pico/etc.; CustomId = platform user id; `CreateAccount=true`; InfoRequestParameters as in item 5 of section 0 |
| `Client/LoginWithSteam` | `PlayFabLoginFacade::LoginWithSteamId` | PC; `SteamTicket`; same InfoRequestParameters |
| `Client/LoginWithPlayFab`, `RegisterPlayFabUser`, `AddUsernamePassword` | `PlayFabLoginFacade` | username/password accounts (PlayerPrefs `CURRENT_PLAYFAB_ACCOUNT_USERNAME`/`_PASSWORD`). **INFERRED:** Arcade/LBE builds only. |
| `Client/UpdateUserTitleDisplayName` | `PlayFabLoginFacade::SetDisplayName` / after `generateDisplayNameV1` | |
| `Client/ExecuteCloudScript` | `PlayFabServerClientAdapter` (all of section 1) and `PlayfabBackendService::GrantBundle` (Quest build, direct `PlayFabClientAPI.ExecuteCloudScript<JsonObject>`) | |
| `Client/GetTitleData` | `PlayFabTitleDataFacade::GetTitleData` | no `Keys` filter (all keys), reloaded periodically |
| `Client/GetUserData` / `UpdateUserData` | `PlayFabUserDataFacade::LoadUserData/StoreUserData` | all keys; writes only locally changed keys plus `KeysToRemove` |
| `Client/GetPlayerStatistics` | `PlayFabPlayerStatisticsFacade` | no name filter; the live log shows "Got 10 items" |
| `Client/GetLeaderboard`, `GetLeaderboardAroundPlayer` | `Assets.RG.Ignis.PlayFab.PlayFabLeaderboardFacade` (via `PlayFabVersionedLeaderboardHandler`, latest and previous `Version`) | StatisticName comes from `LeaderBoardData.statisticsName`. **INFERRED:** `LEAGUE_POINTS_SEASON` (only stat literal in the entry points). `GetFriendLeaderboard` is in the interface but has no caller. |
| `Client/GetTitleNews` | `PlayFabNewsFacade::UpdateNews` | sorted by Timestamp; fields NewsId/Timestamp/Title/Body; the live log shows 10 items |
| `Client/GetCatalogItems` | `PlayFabShopFacade::RequestCatalogue` (store UI and ownership), `PlayfabBackendService::RequestPremiumProducts` (IAP bundles) | no CatalogVersion set on the request, so the primary catalog |
| `Client/PurchaseItem` | `PlayFabShopFacade::BuyItem / BuyTool / BuyFremiumCoins` | `CatalogVersion="1"` (facade field `catalogueVersion`), `ItemId`, `Price`, `VirtualCurrency` `BP`/`FR`; **no StoreId** (no stores are used). Tool purchase ItemId = `ToolName.ToString().ToUpper()` (e.g. `SMG`, `BIGORBUS`). `BuyFremiumCoins` = buy an FR (creds) pack with BP. |
| `Client/GetUserInventory` | `PlayfabBackendService::CallGetUserInventory` | reads `VirtualCurrency["BP"]` for the IAP wallet |
| `Client/StartPurchase`, `PayForPurchase`, `ConfirmPurchase` | `Fidelity.MultiplatformIAP.Internal.IAPSteamPlayFabFacade` | Steam IAP; `ProviderName="Steam"`, `Currency="RM"` |
| `Client/ReportPlayer` | `PlayFabReportFacade::SendReport` (from `PlayFabAbuseReportingHandler`) | Comment = `JsonUtility.ToJson(report)`; reasons `player_name`, `gestures`, `cheating` |
| `MultiplayerServer/CreateMatchmakingTicket`, `GetMatchmakingTicket`, `CancelMatchmakingTicket`, `CancelAllMatchmakingTicketsForPlayer`, `GetMatch`, `GetQueueStatistics` | `PlayFabMatchmakingFacade`, `PlayFabMatchmakingSettingsFacade` | **PlayFab Matchmaking is used** (not Mercury). Player attributes DataObject = `{DisplayName, Character, Region, ELO_RATING, LEAGUE_POINTS_SEASON, LEAGUE_TIER, ClientVersion, RematchBlockString, TournamentWins, TournamentLosses, AcceptedRegions[]}`. Queues: `GlobalRatingPlay`, `3LossYouAreOut`, `Shootout`, `ScrapperShootout`, `WinterClassic`. Needs the login EntityToken. |
| Admin `SetTitleData`, `IncrementPlayerStatisticVersion` | internal tournament debug tool (stage title) | not gameplay |
| Not called by the game: `GetPhotonAuthenticationToken`, `WritePlayerEvent`, `WriteTitleEvent`, `UpdatePlayerStatistics`, `ConsumeItem`, `RedeemCoupon`, `Validate*Receipt/Purchase`, `GetFriendLeaderboard` | | **CONFIRMED** (no callers outside PlayFab.dll) |

---

## 3. Keys, names and codes

### Virtual currencies — **CONFIRMED**
| Code | Meaning |
|---|---|
| `BP` | **Blasts**, the premium currency. Bought with real money (`Blasts_Pack_1..5`). It is `CurrencyShopSettings.VIRTUAL_CURRENCY_KEY`, the `PurchaseItem` currency for premium items, and the tournament entry fee (`entryFeeBlasts`). |
| `FR` | **Creds**, the freemium currency. Earned from matches, levels and missions; can be bought with BP via FR packs. |
| `RM` | real money (PlayFab built-in); used in `PayForPurchase` and in catalog prices of the bundles |

### Catalog — CONFIRMED unless marked
- Catalog version `"1"` (`PlayFabShopFacade.catalogueVersion`). GetCatalogItems requests the primary catalog. **INFERRED:** the primary catalog is `"1"`.
- **IAP bundle item class `premium_coins`** (`CurrencyShopSettings.CURRENCY_BUNDLE_ITEM_CLASS`, also in `ShopHandler`). The bundles are `Blasts_Pack_1..5`, priced at RM 199/499/999/2299/4999 and containing 70/200/450/1160/2850 BP (from the live log). They must match Meta SKUs and the Steam store.
- Tool items: ItemId = uppercase `ToolName` enum name (`SMG`, `SNIPER`, `SHOTGUN`, `BIGORBUS`, `HANDGUN`, `BOW`, …). Mercury uses item class `tool`. **INFERRED:** the PlayFab catalog uses ItemClass `tool` too.
- Cosmetics: the item IDs are the client's `Ignis.Item.id`, with ItemType Character/Banner/Platform/ToolSkin/ItemPack/Arena/Attachment. Examples from the log: `Canix`, `DemonTaurex`, `StandardBanner`, `Nova Themed Banner`, `StandardPlatform`, `BlissPlatform`, `abandonedTheater`, `desertClassic`. The catalog also contains `ResolutionSnowball`, which the client doesn't know.
- **INFERRED:** item custom data / options per the Mercury `ItemOptions` DTO: `{unlockAtLevel:int?, onlyShowIfAssigned, onlyShowItemIfOwned, ownedByDefault}`. This feeds `InventoryItem.requiredLevel/isVisible/isOwned`.
- Stores: none. Drop tables: no client evidence. **INFERRED:** none, or server-only.

### Player statistics
CONFIRMED that these 10 exist: the Mercury `ALL_STATS_IN_GAME_END` list matches the "Got 10 items" log line. All are written server-side.

`ELO_RATING` (start 1200, K=35), `EXPERIENCE`, `RESETTABLE_EXPERIENCE`, `LEAGUE_POINTS_SEASON` (versioned season leaderboard), `LEAGUE_POINTS_TOTAL`, `LEAGUE_POINTS_SHADOW`, `LOSING_STREAK`, `ROUNDS_WON`, `RESETTABLE_ROUNDS_WON`, `TOURNAMENT_GAMES_WON`

Also (CONFIRMED):
- `LEAGUE_TIER`, read in the Mercury code and in the matchmaking attributes.
- Per-queue tournament stats `TOURNAMENT_PVP_MATCHES_WON_<queue>` and `TOURNAMENT_PVP_MATCHES_LOST_<queue>`, e.g. `_3LossYouAreOut`. These are versioned; the admin tool increments their version.

Constants from the Mercury port (CONFIRMED):
- `MAX_LEVEL=23`, `LEAGUE_TIER_RESET_THRESHOLD=2000`.
- XP needed per level: `[0,10,60,120,200,300,420,550,700,860,1040,1240,1460,1690,1940,2210,2500,2805,3135,3485,3835,4185,4535]`. This matches the live log line "level 23, totalExp 4535".

### Title data keys

Read by the client directly in `PlayFabTitleDataHandler` (CONFIRMED):

| Key | Value shape |
|---|---|
| `EXPERIENCE_POINTS_FOR_VICTORY`, `EXPERIENCE_POINTS_FOR_DEFEAT`, `EXPERIENCE_POINTS_FOR_BUYING_TOOL`, `LEAGUE_POINTS_WIN_BASE`, `LEAGUE_POINTS_DEFEAT_BASE` | int as string |
| `LEAGUE_TIER_TRESHOLDS` (sic) | `{thresholds:[{tierIndex,threshold,experienceReward,freemiumReward,premiumReward}]}` |
| `BOT_LEAGUE_POINTS` | `{list:[{botId,leaguePoints}], leaguePointsRange}`. Mercury adds `retentionBotLeagePointSubtractionTerm`, `retentionBotLeagePointReductionPercentage` and `retentionBotProbabilitySlopeCoefficient`. |
| `BOT_MATCH_REWARD_FACTOR_SETTINGS` | `{leastReward, timeWhenAMatchIsConsederedComplete}` |
| `LOG_UPLOAD_SETTINGS` | `{shouldUploadGameLogsAtEndOfEverySuccessfulMatchmakingGame}` |
| `MATCHMAKING_SETTINGS` | queueSettings object (see `getMatchmakingSettingsV1`) |

Read by CloudScript. These come from the Mercury port, so they are **INFERRED** to be the same names in the live title (strong):

| Key | Value shape |
|---|---|
| `LEAGUE_POINTS_SETTINGS` | `{leaguePointsWinBase, leaguePointsDefeatBase, leaguePointsConstant1, leaguePointsCalculationConstant1, minimumWin, minimumLoss, allowDropLeagueTierDownTo, botRewardScalingConstant, leaguePointsDecay, leaguePointsDecayLimit}` |
| `LEAGUE_POINTS_SEASON_SETTINGS` | not known |
| `EXPERIENCE_POINTS_FOR_{VICTORY,DEFEAT}[_BOT][_RANDOM_ADDITION]` | int |
| `FREEMIUM_FOR_{VICTORY,DEFEAT}[_BOT][_RANDOM_ADDITION]` | int |
| `FREEMIUM_FOR_LEVEL_UP`, `PREMIUM_FOR_LEVEL_UP` | int |
| `TOURNAMENT_SETTINGS` | dictionary of `{id,name,gameplayRules,startDay,startHour,duration,lossLimit,entryFeeBlasts,leagueTierLimit,visibleFromInHours,visibleToInHours,stopAcceptingReportsMinutes,winMatchRewardBlasts,…}`. The admin tool writes this key, so its name is CONFIRMED. |
| `RETENTION_BOT_SETTINGS` | `{retentionBotLeaguePointReductionPercentage, retentionBotProbabilitySlopeCoefficients:[{tier,p}]}` |
| `SHOOTOUT_DUELS_SETTINGS` | `{shootoutDuelsEnabled:[int], winterClassicDuelsEnabled:[int], scrapperShootoutDuelsEnabled:[int]}` |
| `TOOL_ATTACHMENT_SETTINGS` | `{Attachments:[{ToolName, Attachment, OwnedByDefault, UnlockMissions:[{MissionId,AmountToComplete,Qualifier[]}], Claimed}]}` |
| `MISSION_SEASONS_SETTINGS` | `{numberOfActiveMissions, missionsUnlockAtLevel, seasons:[{seasonId,startTime,endTime,mandatoryMissions,randomMissions:[{missionId,amountToComplete,qualifier[]}],rewards:[PlayerMissionReward],totalNumberOfMissions}]}` |
| `MISSION_SEASONS_TEMPLATE_SETTINGS` | `{reoccurring:"monthly", mandatoryMissions, randomMissions, rewards, totalNumberOfMissions}`. Season ids are generated from year plus quarter month (`01/04/07/10`). |
| `STORY_EVENT_SETTINGS` | `{acts:[{actId, stages:[{stageId, objectives:[{objectiveId,amountToComplete,rewardWhenObjectiveComplete:{grantAccessToItems,freemiumReward,premiumReward}}]}]}], objectiveSortOrder:[]}` |
| `BOWSER_SETTINGS` | `{enabled, limit, ignore_limit}` |
| `GAME_LOG_UPLOAD_SETTINGS`, `NETWORK_DIAGNOSTICS_SETTINGS`, `PING_VALUE_SETTINGS` | feed `getPlayerSettingsV1` |
| `DUEL_RG_PICO_RTC`, `OZO_RG_PICO_RTC`, `OZO_OFFLINE` | not known (Pico/offline flags) |

### User data keys

Client-written via `UpdateUserData` (CONFIRMED):
- `CUSTOMIZATION_DATA_ACTIVE_LIST_KEY` = `{list:[itemId,…]}`, the equipped cosmetics.
- `CUSTOMIZATION_DATA_ACTIVE_TOOL_ITEM_LIST_KEY` = `{list:[{toolName:<int enum>, customization:itemId}]}`.

Client-read (CONFIRMED):
- `EXPERIMENTAL_UI_SETTINGS` = `{spectatorView}`.

Server-side, from the Mercury port (**INFERRED**; may live in ReadOnly/Internal data on the live title):

| Key | Purpose |
|---|---|
| `DECKS` | `[{deckName,tools}]`; default classic deck = smg, sniper, shotgun, bigorbus, handgun, bow, all with the `default` attachment |
| `OWNED_TOOL_ATTACHMENTS`, `SELECTED_TOOL_ATTACHMENTS` | tool attachments |
| `TOOL_MASTERY`, `TOOL_MASTERY_MISSIONS`, `TOOL_MASTERY_UNLOCKED_TOOLS` | tool mastery state |
| `ASSIGNED_ITEMS` | assigned items |
| `REWARDS` | `{rewards:[{rewardId,rewardType,claimed,time,data:{newLevel,freemium,premium,exp}}]}`; rewardType ∈ `level_up`, `league_up`, `experience_awarded`, `season_end`, `tool_purchase` (CONFIRMED in `PlayFabProgressionData`) |
| `PROCESSED_EXPERIENCE_AWARDS` | dedupe list for `awardExperienceV1` |
| `USER_MESSAGES` | messages for `getUserMessagesV1` |
| `MISSION_SEASON_<seasonId>`, `COMPLETED_MISSION_SEASONS` | mission seasons |
| `STORY_EVENT_DATA` | story progress |
| `TOURNAMENT_TICKETS` | bought tournament entries |
| `PLAYER_MATCHMAKING_SETTINGS` | player matchmaking settings |

---

## 4. In-app purchase flow

### Shared setup (both platforms) — CONFIRMED
`PlayFabServerClientAdapter`'s constructor sets `CurrencyShopAPI.Settings = {BUY_COINS_FUNCTION="buyCoinsV2", CURRENCY_BUNDLE_ITEM_CLASS="premium_coins", DEBUG_GRANT_COINS_FUNCTION="debugAddCoinsV1", VIRTUAL_CURRENCY_KEY="BP"}` and creates a `PlayfabBackendService`.

That service:
1. calls `GetCatalogItems` and keeps the items with ItemClass `premium_coins`;
2. reads `VirtualCurrencyPrices["RM"]` and `Bundle.BundledVirtualCurrencies["BP"]` (the log shows "Added bundleID Blasts_Pack_1 with price 199 containing 70 coins");
3. checks those against the platform store, warning on any "Price mismatch".

### Quest (Meta IAP)
CONFIRMED from ARM64 `IAPOculusFacade` and `PlayfabBackendService`:
1. `IAP.GetProductsBySKU(Blasts_Pack_1..5)`, then `IAP.LaunchCheckoutFlow(sku)`.
2. On success, `HandleTransactionCompletion` calls `GrantBundle(productId=sku, transactionId=$"{purchase.Sku}-{purchase.GrantTime}")`.
3. That calls `ExecuteCloudScript("buyCoinsV2", {productId, transactionId})`.
4. If `status` is `processed` or `already_processed`, the client calls `IAP.ConsumePurchase(sku)`. Otherwise it retries every 3 s, up to `MAX_AMOUNT_RETRIES_ON_CONSUMPTION_FAIL`.
5. At startup, `IAP.GetViewerPurchases` re-submits any purchase that was never consumed ("ConfirmTransactionWithRemoteService" in the log).

What `buyCoinsV2` does on the server is **INFERRED**. It probably checks the purchase with Meta's server-to-server IAP API (`verify_entitlement` / `viewer_purchases`) using the app secret. It then grants the bundle's BP and records `transactionId` so the same purchase can't be granted twice. **We can't reproduce the Meta check without RG's Meta app credentials.** A revival must either trust the client or disable IAP and grant BP some other way.

### PC (Steam via PlayFab native payments) — CONFIRMED
1. `StartPurchase{Items:[{ItemId:bundle, Quantity}]}`
2. `PayForPurchase{OrderId, ProviderName:"Steam", Currency:"RM"}`
3. The Steam overlay sends `MicroTxnAuthorizationResponse_t`.
4. `ConfirmPurchase{OrderId}`; PlayFab grants the bundle's BP itself. Unconfirmed order ids are stored locally and retried.

This needs the PlayFab **Steam add-on** with RG's Steam publisher Web API key. **INFERRED:** it won't work on a new title. `LoginWithSteam` on a new title has the same problem (it can't validate Steam tickets for Blaston's app without the publisher key), so PC most likely needs patching to use `LoginWithCustomID` (Steam ID) or a proxy.

---

## 5. Data to export before shutdown

None of this can be derived from the client. Export with a logged-in client and Charles/mitm, or with RG's cooperation.

- [ ] **CloudScript source.** Revision of legacy CloudScript (`Admin/GetCloudScriptRevision`) needs the secret key, so RG would have to provide it. Without it: capture request/response pairs for **every** function in section 1. Pay most attention to `reportGameEndV1`, `reportBotGameEndV1`, `nonMasterReportGameV1`, `buyCoinsV2`, `getInventoryV2` and the mission/story functions, and capture before/after `GetPlayerStatistics` + `GetUserData` + inventory for each report. The `MercuryServerClientAdapter` port fills most of the logic gaps.
- [ ] **All title data.** It comes back in full in the `LoginWithCustomID` response (`InfoResultPayload.TitleData`) and from `GetTitleData`. Save the raw JSON. Check that every key in section 3 is present; any CloudScript-only key that isn't client-visible (e.g. `LEAGUE_POINTS_SETTINGS` if stored as internal data) is missing from a client dump and needs RG.
- [ ] **Catalog.** Save the full `GetCatalogItems` response: primary catalog, and version `"1"` explicitly. It holds every ItemId, ItemClass, VirtualCurrencyPrices (BP/FR/RM), Bundle contents (`Blasts_Pack_*`, FR packs), CustomData, Tags and IsStackable.
- [ ] **Stores and drop tables.** None are referenced by the client, so nothing to capture unless RG reports some.
- [ ] **Statistic definitions.** Names are known (section 3). Reset intervals and aggregation (`LEAGUE_POINTS_SEASON` versions, `TOURNAMENT_PVP_*`) need the Admin API. From the client side, record `version` and `nextReset` from `getLeaguePointsSeasonV1`, plus `GetLeaderboard` with `Version` for current and previous.
- [ ] **Leaderboards.** Snapshot `getLeaguePointsSeasonV1`, plus `GetLeaderboard(LEAGUE_POINTS_SEASON)` and `GetLeaderboardAroundPlayer` for the current and previous version.
- [ ] **Title news.** Save `GetTitleNews` (10 items: NewsId, Timestamp, Title, Body).
- [ ] **Matchmaking queue configs** for `GlobalRatingPlay`, `3LossYouAreOut`, `Shootout`, `ScrapperShootout` and `WinterClassic`. Rules and attribute paths need the Admin API, so ask RG. Without that, infer the rules from the attributes in section 2 and from `MATCHMAKING_SETTINGS`.
- [ ] **Per-player state for your own account(s):** `GetUserData` (all keys), `GetUserReadOnlyData` if it is used, `GetUserInventory` (items and BP/FR), `GetPlayerStatistics`, and the responses of `getInventoryV2`, `getDecksV1`, `getToolAttachmentsV1`, `getToolMasteryMissionProgressV1`, `getCurrentMissionSeasonV1`, `getCurrentStoryV1`, `getPlayerInfoV1`, `getPlayerSettingsV1`, `getTournamentInfoV1`, `getMatchmakingSettingsV1` and `getUserMessagesV1`.
- [ ] **PlayerPrefs cache.** On PC, export `HKCU\Software\Resolution Games\Blaston` (path is **INFERRED**). The `PlayFabCloudScriptCache_*` values hold real responses.
- [ ] **Token format.** Record `getApiBlastonTokenV1` / `getUserTokenV1` responses (`token`, `valid_until`) to learn the token format that `api.blaston.com` accepts. **INFERRED:** a JWT or HMAC shared between CloudScript and api.blaston.com.

---

## 6. Open questions

- How enums in `claimToolAttachmentsV1.attachmentsToClaim` are serialized (numbers or strings).
- Whether the server keys in section 3 live in TitleData or TitleInternalData, and in UserData, UserReadOnlyData or UserInternalData. That decides how much a client-side dump can recover.
- The `buyCoinsV2` / `debugAddCoinsV1` argument shapes beyond `{productId, transactionId}`, and how Meta purchases are verified.
- `generateDisplayNameV1`'s return format (plain string or object).
- Whether `PlayFabVersionedLeaderboardHandler` is active in normal play. It wasn't seen in the log; `getLeaguePointsSeasonV1` covers the menu leaderboard.

Sources: `dump/xrefs/string_xrefs.tsv`; `dump/xrefs/call_xrefs.tsv`; `dump/isil/IsilDump/Assembly-CSharp/{RG/Ignis/PlayFab,RGCommon/PlayFab,RGCommon/ServerClient,Ignis,IgnisBowser/Story,RG/IgnisBowser}/*.annotated.txt`; `dump/isil/IsilDump/ResolutionGames.MultiplatformIAP/**`; `dump-quest/xrefs/asm/ResolutionGames.MultiplatformIAP/*` (Quest-only `IAPOculusFacade` and `PlayfabBackendService.GrantBundle`); the `_PrivateImplementationDetails_` array blob (level table); and the anonymous-type field names in `dump/cs/DiffableCs/Assembly-CSharp/__f__AnonymousType*.cs`.
