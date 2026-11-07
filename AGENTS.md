# AGENTS.md

Guidance for AI agents working on this repository. What the project is and how
to run it is in [README.md](README.md); everything else is in [docs/](docs/README.md).
This file holds only the rules and traps that are easy to break from inside the
code.

## Before You Finish

```bash
python3 -B -m unittest discover -s tests
```

Add or update tests when changing queue semantics, builder behaviour,
validation or downloads. Fake mode (`MB_BUILDER_MODE=fake`) proves the queue,
not the firmware: a change to the builder, the patches or the prefs pipeline is
only done after one real Docker build.

Keep `docs/` in sync with behaviour. If you add a dependency (there are none
today, by design), update `README.md`, `docs/local-development.md`,
`docs/configuration.md` and the tests.

Never commit runtime data: `var/`, ZIPs, caches, `__pycache__`, `.env`.

## Security Invariants

- The web process never invokes Docker. Only the worker does.
- Device ids map to allowlisted PlatformIO environments in `data/devices.json`.
  Users never submit arbitrary environments or Git refs.
- Users never supply firmware patches, only allowlisted option flags.
- Synthetic `USERPREFS_*` macros are merged after user overrides, so
  `prefsJsonc` cannot set them.
- Preference values stay shape-checked in `meshtastic_builder/jsonc.py`.
  `bin/platformio-custom.py` emits `meshtastic_`- and `{`-prefixed values into
  `-D` flags unquoted. Do not relax those regexes.
- Keys the firmware reads as C strings must reject values the script would emit
  unquoted (digits, bools, hex, enums, byte arrays). See `STRING_MACRO_KEYS`.
- A failed `git apply` fails the build before `pio run`, never continues.
- Build logs hold the full `-D` dump (WiFi PSK, MQTT password). Never serve them
  over HTTP, and only lift diagnostic-shaped lines into `error_message`.
- Public URLs use cryptographically random tokens, never DB ids. Status
  endpoints never expose the full `userPrefs.jsonc`.
- `/api/health` is public: aggregate counts only, no failure details.
- Downloads fail after expiry. The builder input mount stays read-only.
- Builder containers keep CPU, memory, PID and network limits unless there is a
  documented reason to change them.

Background: [docs/security.md](docs/security.md).

## Firmware Patches

Two repo-controlled patches live in `docker/patches/`. Rules:

- A patch is upstream-accepted code copied verbatim wherever one exists, never a
  locally invented edit. The compiled firmware should differ from upstream only
  by code upstream itself accepted.
- Every patch is described on `/about` (`static/i18n.js`): it changes what runs
  on someone's radio.
- `userprefs-ext.patch` applies from `v2.6.4` to `v2.7.26` and **fails on
  2.8.0**. That failure is why the version switch (`nativeSinceFirmwareVersion`)
  exists; do not "fix" it by widening the range.
- `fixed-gps-nodedb.patch` is upstream
  [PR #11825](https://github.com/meshtastic/firmware/pull/11825). Set
  `fixedGpsPatch.fixedSinceFirmwareVersion` in `data/build_options.json` to the
  first release that carries it, or `git apply` starts failing on newer tags.
- Fixed position itself is **not** version-gated and must not be: below 2.8.0
  the firmware compiles that block as shipped. Only the patch is gated.

Details: [docs/build-options.md](docs/build-options.md).

## Devices

`data/devices.json` is generated from the firmware's own metadata, never edited
by hand: `python3 -m meshtastic_builder sync-devices <firmware-checkout> --write`
(`meshtastic_builder/device_sync.py`). Inclusion rule: every env under `variants/**/platformio.ini` that
declares `custom_meshtastic_display_name`, sets
`custom_meshtastic_actively_supported = true` and is not `board_level = extra`.
That is the same set the [Meshtastic Web Flasher](https://flasher.meshtastic.org)
offers. Labels and `family` come from `custom_meshtastic_display_name` and
`custom_meshtastic_architecture`.

- The first eight entries keep their original ids and lead the list, because
  stored build rows reference them. The Pro-micro DIY is first: it is the page's
  default selection.
- Where several envs share a display name, the label gets a suffix.
- The list describes the newest supported tag; an env added upstream later will
  not build against an older tag.
- Environments are not all in the root `platformio.ini`: it includes files under
  `variants/**`. Validate with `python3 -m meshtastic_builder validate-devices`.

## Builder Image

- `docker/build_firmware.sh` is copied in **after** the hour-long prewarm layer,
  so editing it rebuilds in seconds. Do not move that `COPY` above the prewarm.
- PlatformIO is pinned to 6.1.19: 6.2.0 breaks ESP32-S3 builds
  ([platform-espressif32#529](https://github.com/pioarduino/platform-espressif32/issues/529)).
  Bump the pin only after a real `heltec-v4` build passes.
- Do not reintroduce `PLATFORMIO_BUILD_CACHE_DIR`: on a cache hit SCons skips the
  post-actions that write the `.uf2` and `.factory.bin`, and the ZIP ships with
  nothing flashable. See
  [docs/worker-and-builder.md](docs/worker-and-builder.md#why-there-is-no-platformio-build-cache).
  Build speed comes from ccache instead (`docker/ccache_wrap.sh`), which caches
  below SCons. A change to it needs a real second build of the same board that
  still ships its `.uf2`/`.factory.bin`, not only the unit tests.
- Firmware tags resolve to a commit SHA, stored with the build; the worker
  builds the SHA. Historical tags may need dependencies the image lacks, so do
  not assume every tag builds.

## Compose Traps

- The worker image needs Debian's `docker-cli`. `docker.io` on trixie ships only
  the daemon, so the worker starts fine and then fails every build with
  `[Errno 2] No such file or directory: 'docker'`.
- The Compose worker must use `MB_DOCKER_TRANSPORT=copy`. With `bind`, the
  daemon resolves the job input against the host filesystem and the builder
  starts with an empty input directory.
- The worker mounts `MB_DOCKER_SOCKET`. On rootless Docker the default
  `/var/run/docker.sock` does not exist, and the worker fails to start after the
  next reboot.

## Primary Sources

- Firmware build docs: <https://meshtastic.org/docs/development/firmware/build/>
- Firmware repo: <https://github.com/meshtastic/firmware>
- PlatformIO docs: <https://docs.platformio.org/>

## Style and Scope

Prefer small, testable changes. The codebase uses only the Python standard
library, SQLite and vanilla HTML/CSS/JS; do not introduce a framework or
package manager unless the benefit is clear and documented.

## CodeGraph

This project is indexed by CodeGraph. The index lives in `.codegraph/`, which is
gitignored: it is a local SQLite database kept current by a file watcher, not a
build artifact to commit.

Prefer it over grep or reading files when locating or understanding code. One
call returns the relevant symbols' verbatim source plus the call paths and blast
radius:

```bash
codegraph explore "<symbol names or question>"
codegraph sync .    # only if the watcher has not caught up
```

The `codegraph_explore` MCP tool gives the same output when available.
