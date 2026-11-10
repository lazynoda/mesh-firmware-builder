# Firmware Sources

Users pick the firmware to build from a list kept in `data/firmwares.json`.
Every entry is a GitHub repository that builds the same way as upstream
Meshtastic: PlatformIO environments, `userPrefs.jsonc` at the root and
`version.properties` with the firmware version.

```json
{
  "default": "meshtastic",
  "firmwares": [
    {
      "id": "meshtastic",
      "name": "Meshtastic® Oficial",
      "url": "https://github.com/meshtastic/firmware",
      "versioning": "tags"
    },
    {
      "id": "nodastic",
      "name": "Nodastic",
      "url": "https://github.com/lazynoda/meshtastic-firmware",
      "versioning": "branch",
      "branch": "nodastic"
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `default` | Id selected when the page opens, and assumed by API clients that send no `firmwareId`. |
| `id` | Stable id stored with every build. Lowercase letters, digits and `-`, up to 32 characters. Never rename it once builds exist. |
| `name` | Label shown in the selector. |
| `url` | `https://github.com/<owner>/<repo>`. Shown under the selector, and the repository the builder fetches from. |
| `versioning` | `tags`: users pick one of the repository's tags. `branch`: no releases, every build compiles the current head of `branch`. |
| `branch` | Only for `branch` versioning. |
| `license` | Optional, written to `BUILD_INFO.txt`. Default `GPL-3.0-or-later`. |
| `unavailableBoards` | Optional. Boards this firmware lists but cannot build yet, keyed by PlatformIO env: `{"<env>": {"reason": "<code>", "issue": "<GitHub issue URL>"}}`. See [Unavailable boards](#unavailable-boards). |

Without the file the builder offers upstream Meshtastic only.

## How versions work

- **Tags.** Each firmware keeps its own tag cache in SQLite
  (`firmware_versions`, keyed by firmware and tag), refreshed from the GitHub
  releases and tags APIs. A version is offered only when:
  - it is a **published GitHub release** (drafts and bare tags are skipped);
  - its tag reads `vX.Y.Z`, optionally followed by `.<commit>` (upstream's
    `v2.8.2.d5f1619`) or a SemVer pre-release `-<id>` (`v2.8.201-rc.3`). The
    version gates read the leading `x.y.z`; a tag in any other shape
    (`rc-v2.8.201-003`) would be compared as old firmware, so it is skipped.

  The commit comes from the tags API, because a release does not carry it. A
  version that loses its release or tag is marked unsupported (never deleted),
  once both lists were read to the last page.
  The admin commands take `--firmware <id>`, e.g.
  `python -m meshtastic_builder list-versions --firmware jentastic`.
- **Revoked releases.** Upstream withdraws a release by appending "(Revoked)"
  to its title and publishing a new one. Those stay selectable, labelled
  "(revocada)" / "(revoked)", are never the default pick, and selecting one
  names the later release of the same or a newer version that replaces it.
- **Order.** Newest first by `x.y.z`, compared as numbers. Tags of the same
  `x.y.z` (a re-release, `-rc.9` / `-rc.10`) are ordered by release date, never
  by tag text. The date never decides across versions.
- **Branch.** The version selector shows `N/A` and is disabled. The server
  resolves the branch head (cached for five minutes) and reads the firmware
  version from that commit's `version.properties`. The build stores the commit
  it resolved, so the ZIP always says exactly what was compiled.

The version gates (the two patches, eight channels, advanced options) compare
the firmware version `x.y.z`: the tag for tag firmwares, `version.properties`
for branch firmwares. A fork that numbers its versions differently from
upstream (Jentastic's `2.8.104` is upstream 2.8.1 plus its own release 04)
still compares correctly as long as its number does not sort below the upstream
release it is based on.

## Boards

The device list is per firmware and per version. The first time a commit is
requested, the server reads its `variants/` tree through the GitHub API (two
calls) and downloads its `platformio.ini` files from raw.githubusercontent.com
(about 200 for upstream, a few seconds). It reads them the way PlatformIO does,
resolving `extends` (an env's own section, then its `extends` chain, then the
global `[env]`), because many boards declare their keys in a shared base
section (ThinkNode M9, T5 E-paper S3) or inherit them from a parent env (RAK
WisMesh Pocket from `rak4631`). An env is offered when it then has
`custom_meshtastic_display_name`, `custom_meshtastic_actively_supported = true`
and no `board_level = extra`; an env that takes its display name from another
offered env is a build variant of that board (`rak4631_eink`), not a board. The
result goes into SQLite table `board_catalogs`, keyed by firmware and commit. A commit never changes, so it is never read again; the ini
files themselves are also cached on disk by blob SHA, so another tag of the
same firmware only downloads what changed.

Boards already in `data/devices.json` keep their id and label there. Others get
an id from their env name (`nrf52_promicro_diy_e28` -> `nrf52-promicro-diy-e28`),
and a label shared with another board gets the env name as suffix. A submitted
build is checked against the list of its exact commit and stores the board's
label, so the build page can name boards that only a fork has.

If GitHub cannot be reached and the commit is not cached, the page offers
`data/devices.json` instead.

### Meshtastic UI

Some boards have a second build with Meshtastic UI (MUI), the touch interface:
an `<env>-tft` env with no display name of its own (it inherits the board's).
The Web Flasher offers it as a switch on the board, ticked by default, and so
does the builder: a board gets the "Meshtastic UI" checkbox when it resolves
`custom_meshtastic_has_mui = true` and its `<env>-tft` env exists and is not
`board_level = extra`. Ticking it builds that env instead. Boards whose `-tft`
env is a board of its own (Heltec V4 TFT) or whose only env already is the MUI
build (Crowpanel) are picked from the list directly, and a `-tft` env whose
plain board is `extra` (Seeed Wio Tracker L2) is offered as the board. In
upstream 2.8.1, Jentastic 2.8.104 and Nodastic this gives the switch to
T-Deck, SenseCAP Indicator, PICOmputer S3, WisMesh Tap V2 and ThinkNode M9.

### Hybrid builds (Jentastic)

From Jentastic 2.8.105 some boards have an `<env>-hybrid` env: the board with
JenCore and RNode compiled in (`-DNEXUS_ENABLE_JENCORE=1
-DNEXUS_ENABLE_RNODE=1`). It extends the board and takes its display name, so
it is not a board of its own. The builder offers it as a second checkbox under
the board, "JenCore + RNode (hybrid)", unticked by default, when:

- `<env>-hybrid` exists for an offered board `<env>`;
- it takes its display name from the same place as the board (inherited, not
  its own);
- it is not `board_level = extra`.

Ticking it builds that env, stored with ` (JenCore + RNode)` appended to the
board label. Unlike Meshtastic UI there is no `custom_meshtastic_has_*` key:
the env existing is the signal. A hybrid env with a display name of its own is
listed as a board, and one whose base is not an offered board (Jentastic's
`nrf52_promicro_diy_sx1262-noscreen-hybrid`, `cutretech-esp32s3-hybrid`) is not
offered at all. In Jentastic 2.8.105 this gives the switch to Heltec Mesh Node
T096, Heltec V3, Heltec V4 and Seeed SenseCAP Mesh-Tracker-X1. The other
firmwares have no `-hybrid` envs. Meshtastic UI and hybrid are never combined:
no env is both.

Lists cached by an older version are read again from GitHub once
(`CATALOG_FORMAT` in `board_catalog.py`, bumped whenever the parsing changes).

### Compared with the Web Flasher

The Web Flasher does not read `platformio.ini`: its board list is hand-kept in
[meshtastic/api](https://github.com/meshtastic/api) (`deviceHardware`), filtered
to `activelySupported`, and is the same for every version. The builder reads
each firmware's own files instead, because forks add boards upstream's list
lacks and old tags lack newer boards. For upstream 2.8.1 the two differ by a
few boards: the Flasher also offers boards with no metadata in their ini
(ThinkNode M4/M7, Cardputer ADV) or marked `extra` in the firmware
(T-LoRa V2.1-1.8), and the builder also offers boards the firmware marks
supported that the Flasher's list does not (T-Watch Ultra, ThinkNode M8...).

Only `heltec-v4` and `nrf52_promicro_diy_tcxo` are prewarmed in the builder
image. Any other board, from upstream or from a fork, downloads its libraries
on its first build in each container, which is why builds need
`MB_DOCKER_NETWORK=bridge`.

## Unavailable boards

A board the firmware offers but that cannot be built with it (for now) goes in
that firmware's `unavailableBoards`, with a reason code and the GitHub issue
that tracks the fix. Unlike `EXCLUDED_ENVS`/`EXCLUDED_FAMILIES` in
`device_sync.py`, which hide a board from every firmware, this is per firmware
and the board stays visible:

- `/api/devices` lists it with `"unavailable": {"reason", "issue"}` (plus
  `fixedSinceFirmwareVersion` when set);
- the page shows it as unavailable, never picks it by default, and when it is
  selected explains why under the picker, links the issue and keeps the submit
  button off;
- `POST /api/builds` refuses it with `400`, naming the reason and the issue.

```json
"unavailableBoards": {
  "t-echo": {
    "reason": "firmware_too_big",
    "issue": "https://github.com/lazynoda/mesh-firmware-builder/issues/3",
    "fixedSinceFirmwareVersion": "2.8.105"
  }
}
```

Without `fixedSinceFirmwareVersion` the entry applies to every version of that
firmware. With it (`x.y.z`, no `v`), only versions below it are blocked,
compared the same way as the other version gates (the tag's `x.y.z`, or
`version.properties` for a branch); a version that does not parse counts as
blocked. On a blocked version the page also says from which version the board
builds: naming its tag when that version is already offered, or as "not out
yet" when it is not.

Set `fixedSinceFirmwareVersion` only to a version announced as fixing the
board. Before or right after it is released, run one real build of each board
on it: if one still fails, raise the version (or drop the field) so the page
stops offering a version that does not work. Remove the entry once every
offered version builds the board.

Reason codes the page translates (`device.unavailable.<code>` in
`static/i18n.js`): `firmware_too_big`, the image does not fit in the board's
flash; `platformio_unsupported`, set by the builder itself (not in
`firmwares.json`) when the board's platform needs a PlatformIO Core the
builder image does not carry yet (see
[PlatformIO Core per board](worker-and-builder.md#platformio-core-per-board)).
A new code needs an ES and EN text there and in `UNAVAILABLE_REASONS` in
`board_catalog.py`.

Current entries: Jentastic, Heltec Mesh Node T096, Heltec Mesh Pocket (5000
and 10000 mAh, with and without InkHUD) and LILYGO T-Echo, which overflow
flash on v2.8.104 and earlier
([#3](https://github.com/lazynoda/mesh-firmware-builder/issues/3)). `t-echo-inkhud`
(~44 KB over) is listed too, although the builder does not offer it as a board
today: its env declares no display name of its own. All carry
`fixedSinceFirmwareVersion: "2.8.105"`, the release announced to fit them.

## Adding a firmware

1. Add the entry to `data/firmwares.json` and redeploy `web` and `worker`.
2. Check its tags or branch with
   `curl '<base>/api/firmware-versions?firmware=<id>'`.
3. Run one real build for an nRF52 and one for an ESP32 board. The first build
   of a firmware downloads the commits it does not share with upstream, so it
   takes longer.

The builder image does not need rebuilding: it fetches other repositories into
its upstream clone at build time (see
[Worker and Builder](worker-and-builder.md)).
