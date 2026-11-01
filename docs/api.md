# API

All API responses are JSON unless noted.

## `GET /api/health`

Public liveness probe, also served at `GET /health`. Both accept `HEAD`.

It queries the database rather than only answering from the process, so an
unreachable or corrupt SQLite file is reported instead of hidden. `200` with
`"status": "ok"` when the queue is readable, `503` with `"status": "error"` when
it is not. The failure body names no path, driver or query, because the endpoint
is unauthenticated.

Counts are aggregate only. Nothing here is tied to an individual request: no
tokens, no preferences, no device or firmware choices.

```json
{
  "status": "ok",
  "builds": {
    "total": 42,
    "queued": 2,
    "running": 1,
    "succeeded": 38,
    "failed": 1,
    "expired": 4,
    "available": 33,
    "lastRequestedAt": "2026-09-17T04:31:25+00:00"
  }
}
```

`succeeded` counts every build that produced a firmware, including the ones
whose download has since expired. `expired` is therefore a subset of
`succeeded`, and `total` is `queued + running + succeeded + failed`.

`available` counts the builds a user could download right now. It is at most
`succeeded - expired`, and lower while a build's window has closed but the
expiry sweep has not run yet, since expiry is also applied lazily when a
download is attempted.

`lastRequestedAt` is `null` until the first build is requested.

## `GET /api/devices`

Without parameters, returns enabled devices from `data/devices.json`.

With `firmware=<id>` (and `tag=<tag>` for tag firmwares), returns the boards of
that firmware at that version, read from its own repository (see
[Firmware Sources](firmwares.md#boards)). `fromFirmware` is `false` when GitHub
could not be reached and the static list was returned instead.

A board that firmware lists but cannot build at that version carries
`unavailable`, with a reason code, the GitHub issue tracking it and, when a
later version builds it, `fixedSinceFirmwareVersion` (see
[Firmware Sources](firmwares.md#unavailable-boards)). The same board on a
version at or above `fixedSinceFirmwareVersion` has no `unavailable`.
`POST /api/builds` refuses it on the affected versions only.

A board whose firmware has a Meshtastic UI build it does not list as a board of
its own (the `<env>-tft` env of a board declaring `custom_meshtastic_has_mui`)
carries `"mui": true`. See [Firmware Sources](firmwares.md#meshtastic-ui).

Response:

```json
{
  "devices": [
    {
      "id": "tbeam",
      "label": "LILYGO T-Beam",
      "platformioEnv": "tbeam",
      "family": "esp32"
    },
    {
      "id": "t-deck",
      "label": "LILYGO T-Deck",
      "platformioEnv": "t-deck",
      "family": "esp32-s3",
      "mui": true
    },
    {
      "id": "heltec-mesh-node-t096",
      "label": "Heltec Mesh Node 096",
      "platformioEnv": "heltec-mesh-node-t096",
      "family": "nrf52840",
      "unavailable": {
        "reason": "firmware_too_big",
        "issue": "https://github.com/lazynoda/meshtastic-builder/issues/3",
        "fixedSinceFirmwareVersion": "2.8.105"
      }
    }
  ]
}
```

## `GET /api/build-options`

Returns the advanced build option allowlist from `data/build_options.json`. The
frontend uses it to render controls and to gate behaviour by firmware version:

- `minFirmwareVersion`: below this, the advanced panel is hidden and
  `codeOptions` submissions are rejected.
- `nativeSinceFirmwareVersion`: from this version the firmware reads the macros
  itself, so no source patch is shipped and `okToMqtt` uses `nativeMacro`.
- `eightChannelsSinceFirmwareVersion`: from this version 8 channels are
  accepted instead of 3.
- `longName`: UTF-8 byte limit of the owner long name, `maxBytes` (24) from
  `sinceFirmwareVersion` (2.8.0) and `legacyMaxBytes` (39) before it. The page
  shows a byte counter and `POST /api/builds` refuses a longer name.
- `artifactTtlDays`: added by the server from `MB_ARTIFACT_TTL_DAYS`, not from
  the JSON file. The page prints it next to the submit button and in the result
  panel, so the retention copy cannot drift from what cleanup actually enforces.

See [Advanced Build Options](build-options.md).

## `GET /api/firmwares`

Lists the firmware sources from [`data/firmwares.json`](firmwares.md) and the
default one.

```json
{
  "default": "meshtastic",
  "firmwares": [
    {"id": "meshtastic", "name": "Meshtastic Oficial", "url": "https://github.com/meshtastic/firmware", "versioning": "tags", "branch": null},
    {"id": "nodastic", "name": "Nodastic", "url": "https://github.com/lazynoda/meshtastic-firmware", "versioning": "branch", "branch": "nodastic"}
  ]
}
```

## `GET /api/firmware-versions`

Returns supported cached firmware versions of one firmware, newest first. If
the cache is empty, the server attempts to fetch tags from GitHub. For a branch
firmware it returns a single entry: the branch head, resolved at most every
five minutes, with `version` read from that commit's `version.properties`.

Optional query:

- `firmware=<id>`: firmware source, default `meshtastic`.
- `refresh=1`: force tag refresh.

Response:

```json
{
  "firmwareId": "meshtastic",
  "versions": [
    {
      "firmware_id": "meshtastic",
      "firmwareId": "meshtastic",
      "version": "v2.x.y",
      "branch": false,
      "tag": "v2.x.y",
      "sha": "commit-sha",
      "release_name": "v2.x.y",
      "published_at": null,
      "supported": 1,
      "smoke_test_status": "untested",
      "last_checked_at": "2026-06-12T00:00:00+00:00"
    }
  ]
}
```

## `GET /api/prefs-template?firmware=<id>&tag=<tag>`

Returns the `userPrefs.jsonc` template for a supported tag as plain text,
read from the selected firmware's own repository. `firmware` defaults to
`meshtastic`; a branch firmware needs no `tag` and returns the template at the
branch head.

The server uses a local cache under `var/cache/userprefs/` (one subdirectory
per firmware other than `meshtastic`; branch templates are cached per commit). If fetching from GitHub fails, it falls back to `data/userPrefs.fallback.jsonc`.

## `POST /api/builds`

Creates a queued build request.

Request:

```json
{
  "deviceId": "tbeam",
  "firmwareId": "meshtastic",
  "firmwareTag": "v2.x.y",
  "prefsJsonc": "{\"USERPREFS_CONFIG_OWNER_SHORT_NAME\":\"ABC\"}",
  "codeOptions": {
    "okToMqtt": true,
    "customLora": {
      "bandwidthKhz": 250,
      "spreadFactor": 11,
      "codingRate": 5,
      "channelNum": 0
    }
  }
}
```

`mui` is optional (`true` or `false`, default `false`). With `true` the build
compiles the board's Meshtastic UI env (`t-deck-tft` for `t-deck`) and stores
it as the build's `platformio_env`, with ` (Meshtastic UI)` appended to the
board label. It is refused for a board without `"mui": true` in
`/api/devices`.

`codeOptions` is optional. Both sub-options are independent, missing
`customLora` fields fall back to their documented defaults, and the whole object
is rejected for firmware older than `minFirmwareVersion`. See
[Advanced Build Options](build-options.md).

Validation:

- `deviceId` must be enabled in `data/devices.json`.
- `firmwareId` must be listed in `data/firmwares.json`; when absent it means `meshtastic`.
- `firmwareTag` must exist in `firmware_versions` for that firmware and be
  supported. A branch firmware ignores it and builds the branch head.
- `prefsJsonc` must parse as JSONC.
- The merged preferences must hold a non-empty `USERPREFS_CONFIG_OWNER_LONG_NAME`
  and `USERPREFS_CONFIG_OWNER_SHORT_NAME`.
- Preference keys must start with `USERPREFS_`.
- Preference keys must exist in the selected tag's `userPrefs.jsonc` template when keys can be extracted.
- Values must be scalar.
- Values are shape-checked so they cannot inject extra compiler flags: values
  starting with `meshtastic_` must be plain identifiers, values starting with
  `{` must be byte arrays, other strings may not contain quotes, backslashes,
  `$`, backticks or control characters.
- Enum, range and byte-length rules apply per key (roles, regions, presets,
  rebroadcast mode, signature policy, TX power, intervals, MQTT fields).
- `USERPREFS_CHANNEL_<n>_*` keys are accepted for `n` below the channel cap
  even when the tag template does not list them.
- `codeOptions` keys and values must match `data/build_options.json`.

Synthetic macros generated from `codeOptions` are merged last, so they cannot be
set or overridden through `prefsJsonc`.

The submitted preferences are merged onto the selected tag's cached
`userPrefs.jsonc` template before storage. This allows partial overrides while
still giving the firmware build a complete preference file with all expected
`USERPREFS_*` definitions.

Response:

```json
{
  "build": {
    "token": "private-random-token",
    "status": "queued",
    "deviceId": "tbeam",
    "platformioEnv": "tbeam",
    "firmwareTag": "v2.x.y",
    "firmwareSha": "commit-sha",
    "codeOptions": null,
    "attempts": 0,
    "createdAt": "2026-06-12T00:00:00+00:00",
    "startedAt": null,
    "finishedAt": null,
    "expiresAt": null,
    "artifactSha256": null,
    "artifactSizeBytes": null,
    "error": null
  },
  "buildUrl": "http://localhost:8080/?build=private-random-token",
  "statusUrl": "http://localhost:8080/api/builds/private-random-token",
  "downloadUrl": "http://localhost:8080/download/private-random-token"
}
```

`buildUrl` is the page the user is given. No notification is sent, so this URL
is the only way back to the build.

## `GET /api/builds/<token>`

Returns public build status. It never returns the full `userPrefs.jsonc`.

The response also carries `queue`, which is `null` once the build has finished
(`succeeded`, `failed`, `expired`). For a queued build:

```json
{"ahead": 2, "estimateSeconds": 420, "estimateBasis": "board", "remainingSeconds": 2160}
```

- `ahead`: builds the worker will finish before this one: the running build
  plus every build queued earlier (same `created_at, id` order the worker
  claims in). There is one worker, so builds run one at a time.
- `estimateSeconds`: how long this build itself should take. It is the median
  of the last 10 successful builds of the same PlatformIO environment. With
  none, the median of the same chip family, then of every board, then 15 min.
  `estimateBasis` says which one (`board`, `family`, `all`, `default`). Failed
  builds never count: they stop early.
- `remainingSeconds`: until this build is done: what is left of the running
  build (never negative), plus the estimate of every build ahead, plus its own.
  It is `null` when the queue looks stuck: the running build has taken more
  than twice its estimate, or builds have waited more than 5 minutes with
  nothing running.

For a running build: `ahead` 0, `estimateSeconds`, `estimateBasis`,
`elapsedSeconds`, `remainingSeconds` (0 once past the estimate) and `overrun`
(true once past it).

Only counts and times are returned, never which boards or whose builds are
ahead. `POST /api/builds` returns the same `queue` object for the new build.

## `GET /download/<token>`

Downloads the ZIP when:

- token exists,
- build status is `succeeded`,
- artifact exists on disk,
- artifact has not expired.

Expired artifacts return `410 Gone`. Missing/unavailable artifacts return `404` or `410` depending on state.

`HEAD /download/<token>` is supported for download metadata.
