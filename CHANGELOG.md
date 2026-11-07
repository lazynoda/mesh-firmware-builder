# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Builds share a compiler cache ([ccache](https://ccache.dev)), so a board that
  was built before compiles only what changed: the same board and firmware
  version with other settings now take a fraction of the time (measured times in
  [docs/worker-and-builder.md](docs/worker-and-builder.md#compiler-cache-ccache)).
  It caches each object file below PlatformIO, so every build still runs the
  steps that write the `.uf2` and `.factory.bin`. It is not PlatformIO's build
  cache, which shipped ZIPs without them.
- The build log shows how much of that build came from the cache.

### Added

- `MB_CCACHE_VOLUME` (Docker named volume for the cache; empty turns it off)
  and `MB_CCACHE_MAXSIZE` (default `20G`; ccache drops the least recently used
  objects past it).

### Upgrading

- Rebuild the builder image: it gains `ccache` and the toolchain wrapper in
  layers after the prewarm, so the prewarm is reused.
- Set `MB_CCACHE_VOLUME` in `.env` if you do not use the shipped `compose.yml`,
  which defaults it to `meshtastic-builder-ccache`, and pass `MB_CCACHE_VOLUME`
  and `MB_CCACHE_MAXSIZE` to the worker in a compose file of your own. Docker
  creates the volume on the first build. Then recreate the worker.

## [1.4.1] - 2026-11-05

### Changed

- Versions come from published GitHub releases, not bare tags, and only when
  the tag reads `vX.Y.Z`, `vX.Y.Z.<commit>` or `vX.Y.Z-<pre-release>`. Tags in
  other shapes (`rc-v2.8.201-003`) were offered before and compared as old
  firmware: advanced options refused, 3 channels, 39-byte long name.
- Tags of the same version are ordered by release date instead of tag text, so
  a re-release (`v2.8.2.d5f1619` after `v2.8.2.4c89b69`) and `-rc.10` after
  `-rc.9` come first. "Works from version X" hints use the same order.

### Added

- Withdrawn releases (upstream's "(Revoked)") stay selectable, marked as
  revoked and muted in the list, are never the default pick, and name the release that replaces them.
  `GET /api/firmware-versions` returns `revoked`.

### Upgrading

- The `firmware_versions` table gains a `revoked` column on start. Back up the
  database first, then run `refresh-versions` once, so tags without a release
  are retired and release dates and revoked marks are filled in.

## [1.4.0] - 2026-11-01

### Added

- The build page shows how many builds are ahead of a queued one, and an
  estimate of when it will be ready. The estimate is the median of recent
  successful builds of the same board, falling back to its chip family. A
  running build shows the time left, or "taking longer than usual". The time is
  hidden when the queue looks stuck. Nothing is shown with nobody ahead.
- `GET /api/builds/<token>` and `POST /api/builds` return a `queue` object
  with the position and times (counts only, nothing about other builds).
- A failed build says the error will be looked into, and links to
  [@lazynoda](https://t.me/lazynoda) on Telegram for questions.
- A board a firmware cannot build can be marked unavailable only below a given
  version (`fixedSinceFirmwareVersion` in `data/firmwares.json`). On an older
  version the page says from which version it builds, or that the version is
  not out yet.
- Jentastic hybrid builds: a "JenCore + RNode (hybrid)" checkbox under the
  board builds its `<env>-hybrid` variant (Heltec Mesh Node T096, Heltec V3,
  Heltec V4 and SenseCAP Mesh-Tracker-X1 on v2.8.105). `POST /api/builds`
  takes `"hybrid": true`.

### Changed

- Jentastic: LILYGO T-Echo is marked unavailable too (the firmware overflows
  flash by ~76 KB on v2.8.104), and every Jentastic entry is lifted from
  v2.8.105 on, the release that fits them
  ([#3](https://github.com/lazynoda/meshtastic-builder/issues/3)).
- A build that does not fit in the device's flash no longer tells the user to
  drop options or pick another device: the size comes from the firmware, not
  from their settings.

### Upgrading

- Board lists cached by earlier versions are read again from GitHub once.

## [1.3.1] - 2026-10-29

### Fixed

- Board settings inherited through `extends` in `platformio.ini` were ignored,
  so boards declaring their name or support in a shared base section were
  missing: ThinkNode M9 (with its Meshtastic UI build), RAK WisMesh Pocket V3,
  Pod and Repeater Mini V2 (HP), and LilyGo T5 E-paper S3 Pro V1, V2 and V2
  InkHUD. The lists are now read the way PlatformIO reads them, for every
  firmware.
- Seeed Wio Tracker L2, whose only supported build is its Meshtastic UI one,
  is offered, as in the Web Flasher.

### Changed

- The Meshtastic UI checkbox is ticked by default when a board that has it is
  picked, as in the Web Flasher.

### Upgrading

- Board lists cached by earlier versions are read again from GitHub once.

## [1.3.0] - 2026-10-29

### Added

- Meshtastic UI builds. Boards whose firmware has a Meshtastic UI variant they
  do not list as a board of their own (T-Deck, SenseCAP Indicator, PICOmputer
  S3 and WisMesh Tap V2 in the current firmwares) show a "Meshtastic UI"
  checkbox under the device picker, like the Web Flasher's switch. Ticked, the
  build compiles the board's `-tft` env; the build page names it
  "<board> (Meshtastic UI)". The API takes it as `"mui": true` and
  `/api/devices` marks the boards that offer it.
- A (?) help button next to the checkbox shows its explanation on hover,
  keyboard focus or tap.

### Upgrading

- Board lists cached by earlier versions are read again from GitHub once, on
  the first request for each firmware version, to pick up the new field.

## [1.2.5] - 2026-10-29

### Fixed

- The owner long name had no length limit. Firmware 2.8.0 and newer keep only
  24 bytes of it and turn a character cut in half into `?`, so a name ending
  in emoji could reach the node as `...???`. The form now shows a byte counter
  with the limit of the selected version (24 from 2.8.0, 39 before) and the API
  refuses a longer name.

## [1.2.4] - 2026-10-29

### Changed

- The Bluetooth PIN is a single optional field with no prefilled value (the
  example `121212` is now only a placeholder) and no separate checkbox. A PIN
  typed there goes into `userPrefs.jsonc`; left empty, the key is omitted and
  the firmware keeps its own pairing default.

## [1.2.3] - 2026-10-29

### Fixed

- A long name, short name or channel name starting with `{` (e.g. the short
  name `{λ}`) was refused as "must be a list of bytes", and the firmware's
  build script would have compiled it as a byte array. It is now accepted,
  and the copy the compiler reads escapes the brace so the node gets exactly
  the typed text. PSKs and keys still must be byte arrays.

## [1.2.2] - 2026-10-29

### Added

- A firmware can mark boards it lists but cannot build yet
  (`unavailableBoards` in `data/firmwares.json`, with a reason and a GitHub
  issue). The page still lists them, marked unavailable, explains why under the
  device picker with a link to the issue, and does not let the build be
  requested; the API refuses it too.
- Jentastic: Heltec Mesh Node T096 and Heltec Mesh Pocket (5000 and 10000 mAh,
  with and without InkHUD) are marked unavailable: the firmware does not fit in
  their flash (#3). They still build with Meshtastic Oficial and Nodastic.

### Changed

- A build whose firmware does not fit in the board's flash or RAM is no longer
  compiled a second time: the retry always failed the same way.

### Upgrading

- `docker/build_firmware.sh` changed: rebuild the builder image, or overlay the
  new script onto the existing one (see `docs/worker-and-builder.md`).
- Rebuild and restart `web` and `worker`. No database migration.

## [1.2.1] - 2026-10-29

### Fixed

- `/api/health`: `builds.succeeded` now also counts builds whose download has
  expired, so it is the number of firmwares ever built (the README's
  "firmwares built" badge reads it). `expired` is still reported on its own;
  `available` is unchanged.

## [1.2.0] - 2026-10-26

### Added

- "Import userPrefs" button above the form. It opens a dialog where you paste a
  `userPrefs.jsonc` (or pick the file, which only fills the text box) and fills
  the form from it, so several nodes can share one configuration. It runs in
  the browser only; nothing is sent until you request the build.
  - The JSON is checked before the form is touched: JSONC syntax, an object of
    `USERPREFS_*` keys with plain values, at most 64 KB, and byte arrays (admin
    keys, channel PSKs) of the right length. An error keeps the dialog open
    with the reason.
  - Firmware, version and device are not part of the JSON: the import applies
    to the ones selected.
  - The node's long and short names are never imported: every node needs its
    own.
  - The manual LoRa settings the preview lists as comments are read back too.
  - Keys the selected version does not have, channels above its limit, and
    values that could not be set the same way are listed after the import.

### Upgrading

- Rebuild `web` and `worker`. No builder image or database change.

## [1.1.3] - 2026-10-24

### Fixed

- A Bluetooth PIN that started with `0` reached the compiler as an octal
  number. With an `8` or `9` in it the build failed (`invalid digit "9" in
  octal constant`); without them it compiled silently with a different PIN.
  The form and the API now require six digits without a leading zero
  (`100000`–`999999`), which is also the only length the nRF52 firmware accepts
  as a fixed passkey.
- Any other integer setting with leading zeros is compiled without them, so it
  keeps its decimal value. The stored request keeps what was typed.
- Compiler errors about a `-D` flag itself (`<command-line>: error: ...`) are
  now reported as `compile_error` with that line, instead of `unknown`.

### Upgrading

- Rebuild `web` and `worker`. No builder image or database change.

## [1.1.2] - 2026-10-22

### Fixed

- Text settings without spaces that contained shell characters (`|`, `;`, `&`,
  `<`, `>`, `(`, `)`, `'`, `*`, `?`, `[`, `]`, `~`, `#`, `{`, `}`, `!`, `^`)
  broke the build or were run by the shell. PlatformIO passes such a value to
  the compiler without real quotes, so a long name like `ABC|DEF` piped the
  compiler into `DEF`. The builder now backslash-escapes those characters in
  the `userPrefs.jsonc` it compiles with, so the value reaches the firmware
  exactly as typed. Values with spaces, numbers, enums, byte arrays and
  upstream's `'host'` form are left as they are. The stored request keeps the
  original text; the ZIP's `userPrefs.jsonc` is the escaped copy that was
  compiled.

### Upgrading

- Rebuild `web` and `worker`. No builder image or database change.

## [1.1.1] - 2026-10-21

### Changed

- The node's long and short names are required and no longer prefilled. The
  form used to open with "Mi nodo Meshtastic" / "MESH", and many nodes were
  flashed with that name. Submitting without either name now marks the empty
  field, and `POST /api/builds` refuses a build whose merged `userPrefs.jsonc`
  lacks either name.

## [1.1.0] - 2026-10-21

### Firmwares

- Choose the firmware to build, not only the official one. The list lives in
  `data/firmwares.json` (id, name, GitHub URL, versioning) and ships with
  Meshtastic Oficial (default), [Jentastic](https://github.com/derpyspike/jentastic)
  and [Nodastic](https://github.com/lazynoda/meshtastic-firmware). See
  [Firmware Sources](docs/firmwares.md).
- Firmwares versioned by tags keep their own tag cache in SQLite, keyed by
  firmware and tag. Firmwares built from a branch show the version as `N/A`
  and always build the branch head; the commit is resolved at submit time and
  stored with the build.
- Version gates (patches, channel count, advanced options) compare the
  firmware's own version: the tag, or `version.properties` for branch
  firmwares.
- The `userPrefs.jsonc` template, `BUILD_INFO.txt` (`firmware`, `source`,
  `firmware_version`) and the ZIP name come from the chosen firmware.
- The builder image fetches other repositories into its upstream clone at
  build time. Adding a firmware needs no image rebuild.
- The firmware's GitHub link is shown under its selector.

### Devices

- The device list is read from the chosen firmware at the chosen version
  (`variants/**/platformio.ini`, the Web Flasher's rule) and cached per commit.
  Forks show their own boards (Jentastic adds the Pro-micro E28 2.4 GHz,
  2.4 GHz TCXO, SX1262 and NiceRF LR1121 variants), and older tags only offer
  the boards they had. A board the selected commit lacks is refused at submit
  time instead of failing to compile.
- Builds store the board's label, so the build page names fork-only boards.
- `sync-devices` regenerates `data/devices.json` from a firmware checkout,
  keeping existing ids and labels. Added LILYGO T-Connect Pro.
- nRF54L15 boards are excluded until they can be flashed from the ZIP
  ([#2](https://github.com/lazynoda/meshtastic-builder/issues/2)).

### Interface

- Section 1 is now "Firmware and device": firmware, version, then device.
- Every dropdown uses the same picker as the device selector. Short lists open
  as a menu; long ones can be filtered by typing.
- The running version is shown in the footer, linked to its release.
- The "Refresh tags" button is gone. Tags are refreshed by an operator
  (`refresh-versions`, all firmwares by default), for example from a daily
  timer; see [Operations](docs/operations.md#firmware-version-admin).

### Fixed

- Picking an option in a dropdown now closes it. The click also reached the
  surrounding label, which refocused the input and reopened the list.
- Tags deleted from a firmware's repository stop being offered after the next
  refresh. Their rows stay, unsupported, so old builds still resolve.
- nRF54 builds no longer die on the last step on arm64 hosts: PlatformIO's
  32-bit ARM `srec_cat` is replaced by Debian's native one when it cannot run.
- A build tool that cannot be started is reported as an infrastructure
  failure instead of an unknown one.

### Upgrading

- Rebuild the builder image (`docker build -f docker/builder.Dockerfile …`).
  Only the layers after the prewarm change: `srecord` is installed and
  `build-firmware` takes the repository URL as a fourth argument.
- The database migrates itself on start: `firmware_versions` is rebuilt with
  `(firmware_id, tag)` as key, and `build_requests` gains `firmware_id`,
  `firmware_version` and `device_label`. Back it up first.
- Rebuild and restart `web` and `worker`.

## [1.0.0] - 2026-10-21

First tagged release: the version running on
<https://builder.meshtastic.lazynoda.es>.

### Builds

- Web form that compiles custom Meshtastic firmware from the official
  [meshtastic/firmware](https://github.com/meshtastic/firmware) repository,
  with the user's settings baked into `userPrefs.jsonc`.
- Firmware versions taken from upstream's GitHub tags. The newest 20 are
  offered, and `refresh-versions`, `list-versions`, `set-supported` and
  `set-unsupported` manage the cache.
- 95 devices, the same set the Meshtastic Web Flasher offers, generated from
  the firmware's own variant metadata. The Pro-micro DIY is the default.
- SQLite queue and a worker that compiles each build in a throwaway Docker
  container with PlatformIO. The web process never touches Docker.
- Builder image with the firmware cloned and PlatformIO prewarmed for
  `heltec-v4` and `nrf52_promicro_diy_tcxo`. PlatformIO is pinned to 6.1.19,
  because 6.2.0 breaks ESP32-S3 builds.
- Builds against a remote or rootless Docker daemon (`copy` transport,
  `MB_DOCKER_SOCKET`).

### Settings

- Node long and short name, timezone with Peninsula and Canary Islands presets.
- LoRa region, modem preset, TX power, and manual LoRa parameters (bandwidth,
  spreading factor, coding rate, frequency slot). The form opens on the
  SFNarrow profile at 869.618 MHz.
- `ok_to_mqtt` and `ignore_mqtt`.
- Device role, rebroadcast mode, node info and telemetry intervals.
- Up to 8 channels (3 before firmware 2.8.0) with name, PSK, position
  precision and mute, reorderable by drag and drop.
- Bluetooth PIN, WiFi, MQTT broker, credentials, root topic and TLS.
- Position: GPS mode, broadcast interval, smart position, fixed position.
- Admin keys, managed mode and packet signature policy.
- Any other key in the selected tag's `userPrefs.jsonc`, through a free-form
  key/value section.
- Options and enum values are gated by firmware version. A live preview shows
  the exact `userPrefs.jsonc` that will be compiled, template defaults included.

### Firmware patches

- `userprefs-ext.patch` adds the advanced options to firmware older than 2.8.0,
  which reads them natively.
- `fixed-gps-nodedb.patch` (upstream PR #11825) makes fixed positions compile
  on 2.8.0. It is no longer applied from 2.8.1, which ships the fix.

### Results

- No account and no email. Every build gets a private permalink,
  `/build/<token>`. Old `/?build=<token>` links redirect to it.
- The ZIP holds only flashable files plus `FLASHING.txt` with the steps for its
  chip, `userPrefs.jsonc` and `BUILD_INFO.txt`. ESP32 builds ship the app image
  as `*-update.bin`, so the Web Flasher accepts the ZIP as is.
- ZIPs are kept for 7 days, then cleaned up automatically.
- A failed build shows a translated reason (patch failed, compile error,
  firmware too big, timeout…) and one quoted line of evidence, never the raw
  log, which holds the WiFi and MQTT passwords.

### Security

- Every value is shape-checked so that no setting can inject extra compiler
  flags. Enum, range and byte-length rules apply per key.
- Devices and PlatformIO environments come from an allowlist.
- Builder containers run with CPU, memory and PID limits.
- Per-IP rate limit on submissions. `MB_TRUST_PROXY` is used behind a reverse
  proxy.

### Operations

- Public `/api/health` endpoint with aggregate queue counts and no per-build
  data.
- `build-log`, `docker-status` and `validate-devices` admin commands.
- Spanish and English interface, an `/about` page, and the AGPL source link on
  every page.

### License

- AGPL-3.0-only. The firmware patches stay under GPL-3.0.

[1.4.1]: https://github.com/lazynoda/meshtastic-builder/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/lazynoda/meshtastic-builder/compare/v1.3.1...v1.4.0
[1.3.1]: https://github.com/lazynoda/meshtastic-builder/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/lazynoda/meshtastic-builder/compare/v1.2.5...v1.3.0
[1.2.5]: https://github.com/lazynoda/meshtastic-builder/compare/v1.2.4...v1.2.5
[1.2.4]: https://github.com/lazynoda/meshtastic-builder/compare/v1.2.3...v1.2.4
[1.2.3]: https://github.com/lazynoda/meshtastic-builder/compare/v1.2.2...v1.2.3
[1.2.2]: https://github.com/lazynoda/meshtastic-builder/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/lazynoda/meshtastic-builder/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/lazynoda/meshtastic-builder/compare/v1.1.3...v1.2.0
[1.1.3]: https://github.com/lazynoda/meshtastic-builder/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/lazynoda/meshtastic-builder/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/lazynoda/meshtastic-builder/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/lazynoda/meshtastic-builder/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/lazynoda/meshtastic-builder/releases/tag/v1.0.0
