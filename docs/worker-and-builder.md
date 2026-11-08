# Worker And Builder

## Worker Lifecycle

The worker loop:

1. Requeues stale `running` jobs.
2. Claims the oldest `queued` job transactionally.
3. Creates a temporary job directory.
4. Writes `userPrefs.jsonc` and `BUILD_INFO.txt`.
5. Copies the firmware patches this build needs into `input/patches/` — see
   [Advanced Build Options](build-options.md) for which patch applies when.
6. Runs either fake mode or Docker mode.
7. Stores the ZIP under `artifact_dir/<public_token>.zip`.
8. Records SHA256, size, finish time, and expiry time.
9. Periodically expires old artifacts.

Run once:

```bash
python3 -m meshtastic_builder.worker --once
```

Run continuously:

```bash
python3 -m meshtastic_builder.worker
```

## Fake Mode

Fake mode exercises the queue, ZIP creation, and status update without Docker:

```bash
MB_BUILDER_MODE=fake python3 -m meshtastic_builder.worker --once
```

The fake ZIP contains:

- `BUILD_INFO.txt`
- `userPrefs.jsonc`
- `firmware-<env>.txt`

## Docker Mode

Docker mode supports two transports.

`bind` uses local bind mounts:

```bash
docker run --rm \
  --network <MB_DOCKER_NETWORK> \
  --cpus <MB_DOCKER_CPUS> \
  --memory <MB_DOCKER_MEMORY> \
  --pids-limit <MB_DOCKER_PIDS_LIMIT> \
  -v <job-input>:/work/input:ro \
  -v <job-output>:/work/output \
  -v <MB_CCACHE_VOLUME>:/ccache \
  -e CCACHE_DIR=/ccache \
  -e CCACHE_MAXSIZE=<MB_CCACHE_MAXSIZE> \
  -v <MB_PIO_DOWNLOAD_VOLUME>:/pio-downloads \
  -e MB_PIO_DOWNLOAD_DIR=/pio-downloads \
  <MB_BUILDER_IMAGE> \
  <firmware-tag> \
  <firmware-sha> \
  <platformio-env> \
  <firmware-repo-url>
```

`copy` is for remote Docker daemons. It creates a container, copies local inputs into
the container with `docker cp`, starts the build, copies `/work/output` back, and
then removes the container.

`MB_DOCKER_TRANSPORT=auto` selects `copy` when `DOCKER_HOST` starts with
`ssh://`, `tcp://`, `http://`, or `https://`, and also when the worker itself runs
in a container (`/.dockerenv` exists), because a worker reaching the host daemon
through a mounted socket does not share that daemon's filesystem either. It
selects `bind` only when the worker and the daemon see the same paths.

Picking `bind` wrongly fails silently at first: the daemon resolves the job input
path against its own filesystem, does not find it, creates an empty directory, and
the build dies inside the container with
`cp: cannot stat '/work/input/userPrefs.jsonc': No such file or directory`.

`compose.yml` still pins `copy` for its worker rather than relying on `auto`.

## Compiler Cache (ccache)

Builds share a [ccache](https://ccache.dev) cache, so object files that did not
change since an earlier build (framework, libraries, most of Meshtastic) are
reused instead of compiled again. Every SCons target and every post-action still
runs, so the `.uf2` and the `.factory.bin` are always generated.

How it is wired:

- The worker mounts the Docker named volume `MB_CCACHE_VOLUME` at `/ccache` in
  every builder container and sets `CCACHE_DIR=/ccache` and
  `CCACHE_MAXSIZE=<MB_CCACHE_MAXSIZE>`. A named volume, not a host path, because
  the daemon may be remote or rootless. Docker creates it on first use. Empty
  `MB_CCACHE_VOLUME` turns the cache off and builds compile everything, as
  before. An invalid name or size also turns it off rather than failing builds.
- The builder image installs `ccache`, `docker/ccache_wrap.sh` (as
  `/usr/local/bin/mb-ccache-wrap`) and `docker/ccache_pre.py`. Nothing in the
  firmware is changed: the builder serves any firmware repository.
- `build-firmware` runs the wrapper before `pio run`, and adds
  `ccache_pre.py` as a PlatformIO `pre:` script through `PLATFORMIO_EXTRA_SCRIPTS`,
  which runs the wrapper again once PlatformIO has installed any toolchain the
  build was missing and before the first compile.
- The wrapper replaces every `*-gcc`, `*-g++`, `*-c++` and `*-cc` in each
  `packages/toolchain-*/bin` with a small shell script that calls ccache with the
  real compiler, which moves to `packages/toolchain-*/.mb-real-bin/` together
  with links to the rest of `bin/` (the ARM gcc loads its libraries from its own
  directory, and the per-chip xtensa drivers call `xtensa-esp-elf-gcc` next to
  them). The platforms set `CC` to a bare compiler name and put the package's
  `bin/` first on `PATH`, so a wrapper elsewhere on `PATH` would never be used.
- ccache identifies the compiler by package name and version from its
  `package.json`, so a new toolchain never reuses objects of an old one.
- `ccache` keeps the volume under `CCACHE_MAXSIZE` by dropping the least
  recently used objects. Concurrent builds can share it.
- The build log shows the hits and misses of that build under
  "Compiler cache for this build", plus the size of the whole cache.

A changed `userPrefs.jsonc` is safe and still fast. Each preference reaches every
compile as a `-D` flag. ccache's direct mode hashes those flags, so it misses;
its preprocessor mode then hashes the preprocessed source instead, where a
`-D` only shows up in the files that use that macro. So exactly the files that
read a changed preference are recompiled, and the rest still hit.

Measured on the 2-vCPU ARM64 VM at 1 CPU per build, Jentastic `v2.8.105`:

| Board | No cache | Empty cache (first build) | Same settings again | Other owner name |
| --- | --- | --- | --- | --- |
| `nrf52_promicro_diy_tcxo` | 7.0 min | 8.8 min | 1.5 min | 2.5 min |
| `heltec-v4` | ~19.8 min ¹ | 26.0 min | 3.8 min | 7.6 min |
| `heltec-v3` (not prewarmed) | ~30 min ¹ | 40 min | | 10.1 min ² |

¹ Median of the production builds of that board and version, same VM and CPU
limit; not re-measured in the same run.

² With the shared package downloads (next section) already filled. A board
that is not prewarmed rebuilds its ESP-IDF libraries for itself on every build
(about 2,900 objects instead of 750); ccache serves those too (99.6% hits).

The first build of a board and version is slower than without the cache (about
25% here): every object misses, and on a miss ccache preprocesses the file
before compiling it. Every later build of that board and version, with any
settings, pays it back. On the VM's production queue, more than half the builds
repeat a board and version already built.

Other measurements from the same run:

- Upstream `v2.8.2.d5f1619` Pro-micro, which also downloads its newer ARM
  toolchain during the build (wrapped by the `pre:` script): 10.0 min with an
  empty cache, 3.0 min with other settings after it.
- Two Pro-micro builds at once at 0.5 CPU each, sharing the cache: 5.2 min each,
  both with a `.uf2` holding their own owner name.
- Cache size after those ten builds of three board/version pairs: 195 MB, so
  roughly 50 to 80 MB per board and version.

The firmware is not bit-for-bit reproducible between two builds of the same
commit, with or without the cache, so compare builds by what they carry
(preferences, files), not by hash.

## Shared Package Downloads

Every builder container starts from the image, so a board whose platform,
toolchain or libraries are not prewarmed downloads them again on every build.
The worker therefore also mounts the Docker named volume
`MB_PIO_DOWNLOAD_VOLUME` at `/pio-downloads` and sets `MB_PIO_DOWNLOAD_DIR`.
`build-firmware` points PlatformIO's download store
(`/opt/platformio/.cache/downloads`) at it, so each archive is fetched once and
reused by later builds of any board.

Only the **downloaded archives** are shared, never the installed packages, and
that is deliberate:

- ESP32 boards with a `custom_sdkconfig` rewrite their installed Arduino
  framework for themselves ("Reinstall Arduino framework", "Compile Arduino IDF
  libs for <board>"). Whether a rebuild is needed is decided against a
  `sdkconfig.defaults` that lives in the image's firmware checkout, so a shared
  `/opt/platformio` would let the next board link libraries another board
  rebuilt, with no error. Unpacking into each build's own container, which is
  thrown away afterwards, rules that out.
- PlatformIO files each archive under a hash of its URL and checksum, writes
  it to a temporary file and only renames it into place once complete (verifying
  the checksum when the source gives one), and serialises writers with a lock
  file. A killed build leaves at most a `tmp*` file, which `build-firmware`
  removes after three hours.
- PlatformIO drops archives no build has used for 30 days.

Empty `MB_PIO_DOWNLOAD_VOLUME` turns it off; an invalid name or an unwritable
volume also turns it off rather than failing builds. To empty it, with no build
running: `docker volume rm <volume>`.

Measured on the same VM at 1 CPU, Jentastic `v2.8.105`, with ccache already
holding each board:

| Board | Empty download volume | Download volume filled |
| --- | --- | --- |
| `heltec-v3` (not prewarmed) | 11.0 min, 72 downloads | 10.1 min, 0 downloads |
| `heltec-v4` (prewarmed) | | 7.6 min, 0 downloads |
| `nrf52_promicro_diy_tcxo` (prewarmed) | | 2.5 min, 0 downloads |

The time saved is small (the 72 archives were 31 MB of libraries); what the
volume mainly removes is a build's dependence on GitHub and the PlatformIO
registry answering about 70 requests. A Heltec V4 built right after a Heltec V3
shipped a `bootloader.bin` and `partitions.bin` identical to production V4
builds, so the V3's framework rebuild did not reach it.

## Why There Is No PlatformIO Build Cache

PlatformIO's `build_cache_dir` is a SCons `CacheDir`, and SCons does **not** run a
target's post-actions when it retrieves that target from the cache. Meshtastic
generates its flashable images inside post-actions:

- `extra_scripts/nrf52_extra.py` hangs the `.uf2` off `$BUILD_DIR/${PROGNAME}.hex`
- `extra_scripts/esp32_extra.py` hangs the `.factory.bin` off `$BUILD_DIR/${PROGNAME}.bin`

Those files are side effects, not declared SCons targets, so they are never put
in the cache and never regenerated from it. A build whose targets all come back
from the cache therefore **succeeds and produces nothing flashable**, and nothing
in the build output says so.

Observed on `nrf52_promicro_diy_tcxo` at `v2.8.0.47db0e3`: a 15-second cache-hit
build left `.elf`, `.hex` and `-ota.zip` in `.pio/build` and no `.uf2`, and the
ZIP went out with a `.hex` that needs a SWD or J-Link programmer while
`FLASHING.txt` still told the reader to double-tap reset and copy a file that was
not there. The same failure applies to ESP32, where a missing `.factory.bin` also
flips `write_flashing_notes` into its nRF52 branch.

ccache (above) gives the build time back without the bug, because it caches
below SCons and every target is still genuinely built. Do not reintroduce
`PLATFORMIO_BUILD_CACHE_DIR`.

`MB_DOCKER_NETWORK` defaults to `bridge` because users can select historical
firmware tags whose PlatformIO dependencies may differ from the image build ref.
Set it to `none` only for a prewarmed image that covers the supported tag/device
matrix.

Only the worker needs Docker access.

Builder containers still run with CPU, memory, PID, and network limits. The CPU
limit defaults to 4 because firmware builds are CPU-bound: with 2 CPUs an nRF52
build takes several minutes longer.

A remote daemon (`DOCKER_HOST=ssh://...`) works with `MB_DOCKER_TRANSPORT=copy`
and `MB_DOCKER_NETWORK=bridge`; see [Docker Compose Flow](compose-flow.md#remote-docker-daemon).

## Builder Image

`docker/builder.Dockerfile`:

- starts from Debian,
- installs Git, Python, PlatformIO CLI, Zip tools,
- clones [meshtastic/firmware](https://github.com/meshtastic/firmware) with tags and submodules,
- checks out `MESHTASTIC_REF` (`latest` = newest release tag at image build time),
- prewarms PlatformIO dependencies for `PREWARM_ENVS` against that ref, using
  `docker/prewarm.sh`,
- installs PlatformIO pinned to `PLATFORMIO_VERSION` (6.1.19),
- disables PlatformIO telemetry and upgrade checks,
- installs `ccache` and the toolchain wrapper (see
  [Compiler Cache](#compiler-cache-ccache)), after the prewarm,
- installs `docker/build_firmware.sh` as the entrypoint, in a layer **after** the
  prewarm.

That last ordering is deliberate. The prewarm layer costs about an hour and 8 GB,
and Docker discards it whenever an earlier layer changes. Prewarming therefore
has its own script, so editing the runtime entrypoint — which happens whenever a
patch, a phase banner or a failure marker changes — rebuilds in seconds instead
of re-prewarming. Edits to `docker/prewarm.sh` still cost a full rebuild; keep
that file boring.

`latest` resolves with `git tag --sort=-v:refname`, which compares the trailing
short SHA as a version component rather than by date. Two tags sharing a version
(`v2.8.0.7239fe8` and `v2.8.0.47db0e3`) therefore sort by that SHA, not by
release order. Pass `MESHTASTIC_REF` explicitly when it matters which tag gets
prewarmed; it only affects cache warmth, never which tag a build compiles.

The default `PREWARM_ENVS` is `heltec-v4 nrf52_promicro_diy_tcxo`: the two most
requested devices, covering the ESP32-S3 and nRF52 toolchains. For production
images, pass a wider list explicitly:

```bash
docker build \
  --build-arg PREWARM_ENVS="tbeam heltec-v3 heltec-v4 heltec-mesh-node-t114 tracker-t1000-e heltec-wsl-v3 rak4631 nrf52_promicro_diy_tcxo" \
  -f docker/builder.Dockerfile \
  -t meshtastic-firmware-builder:local .
```

At runtime, the entrypoint checks out the requested SHA/tag directly inside
`/opt/firmware`. It only runs `git fetch` when that SHA is not already in the
image, which is what lets the image build firmware tags released after the
image itself; the fetch is best-effort, so a prewarmed offline image still
works for the tags it already has. Each Docker build runs in its own ephemeral container
filesystem, so this does not mutate shared service state, avoids copying the
firmware checkout per request, and lets PlatformIO reuse warmed `.pio` artifacts
from the single builder image when they are still valid.

### PlatformIO Core per board

The image carries more than one PlatformIO Core: `pio` is 6.1.19, and each
further one lives in its own venv as `/opt/pio-cores/<x.y.z>/bin/pio` (6.2.0
today). They share `/opt/platformio`, so packages are not duplicated.

Each board is built with the **lowest** Core its platform accepts:

- A platform declares only a minimum (`engines.platformio` in its
  `platform.json`), never a maximum, and a newer Core can still break an older
  platform halfway through. Core 6.2.0 brings tool-scons 4.11, which dropped
  `SCons.Tool.FortranCommon`; the pioarduino 55.03.311 ESP32 platform
  (upstream 2.8.0-2.8.1, Jentastic 2.8.103-2.8.105) declares `>=6.1.19`, starts
  fine on 6.2.0 and fails at link time with
  `No module named 'SCons.Tool.FortranCommon'`
  ([platform-espressif32#529](https://github.com/pioarduino/platform-espressif32/issues/529)).
- pioarduino 55.03.312-1 (upstream 2.8.2, Jentastic 2.8.201, Nodastic)
  declares `>=6.2.0`, and 6.1.19 refuses it before compiling anything with
  `IncompatiblePlatform ... depends on PlatformIO Core >=6.2.0`.

Which Core a board needs is worked out when the board list of a commit is read
(`meshtastic_builder/platformio_versions.py`, stored in the same
`board_catalogs` row): the root `platformio.ini` and every file its
`extra_configs` loads, the board env's `platform` after resolving `extends`,
then that platform's `platform.json` from GitHub (registry platforms
`platformio/<name>@x.y.z` from the `v<x.y.z>` tag of
`platformio/platform-<name>`; archive, release and `git#ref` URLs from their
own repository). A platform for Core 2-5 counts as compatible with any 6.x, as
PlatformIO itself does (`ststm32` declares `^5`). The worker passes the answer
as `MB_PLATFORMIO_VERSION`, and `BUILD_INFO.txt` and the log name the Core
that ran.

When the answer is unknown (a `platform` the lookup does not resolve, such as
a version range, or a `platform.json` it could not read), the worker passes
nothing and the entrypoint starts on the lowest Core; if PlatformIO answers
`IncompatiblePlatform`, it moves up one Core and runs again. That costs
seconds, because PlatformIO refuses before compiling. A Core that was named is
never changed at build time. A network failure during the lookup is not
stored, so the next request reads it again. When a platform needs a Core the
image does not have, the board is listed as unavailable
(`platformio_unsupported`) instead of being queued to fail.

To add a Core: append it to `PLATFORMIO_EXTRA_CORES` in
`docker/builder.Dockerfile` and to `PLATFORMIO_VERSIONS` in
`platformio_versions.py`, bump `CATALOG_FORMAT` in `board_catalog.py` so
stored answers are worked out again, and run a real build of one board per
platform family on it.

Even on the right Core the first run after a platform change can fail while
pioarduino swaps tool-scons, so both prewarm and the runtime entrypoint retry
`pio run` once on the same Core. The runtime entrypoint skips the
retry when the linker reports `region ... overflowed by N bytes`: linking the
same objects again fails the same way, so it stops at once with
`firmware_too_big` (`tests/test_build_script.py` runs that block with a fake
`pio`).

On arm64 hosts PlatformIO's `tool-sreccat` package carries a 32-bit ARM
`srec_cat`, which a 64-bit-only image cannot run (`sh: 1: …/srec_cat: not
found`, `Error 127`). nRF54 boards call it to write their `.hex`, so their builds
died on the last step. The image installs Debian's `srecord`, and the
entrypoint replaces the bundled binary with a link to the native one whenever
the bundled one does not run, before `pio run` and again before its retry (a
platform installed by the first run can bring the package along). On x86 the
bundled binary runs and is left alone. A tool that cannot be started is
reported as an `infrastructure` failure, not `unknown`.

Entrypoint contract:

```bash
build-firmware <firmware-tag> <firmware-sha> <platformio-env> [<firmware-repo-url>]
```

`<firmware-repo-url>` is the `.git` clone URL of the firmware chosen in
[`data/firmwares.json`](firmwares.md); without it the build uses upstream
Meshtastic. The image only ever clones upstream. For another repository the
entrypoint fetches exactly `<firmware-sha>` from that URL into the same
`/opt/firmware` clone, without its tags, checks out that commit and resyncs the
submodule URLs from the commit's own `.gitmodules`. There is no fallback to the
tag name for other repositories, because it could resolve to an upstream tag
and compile the wrong firmware. The first build of each firmware downloads the
history it does not share with upstream, so it needs network access
(`MB_DOCKER_NETWORK=bridge`). Adding a firmware never requires rebuilding the
image.

Inputs:

- `/work/input/userPrefs.jsonc`
- `/work/input/BUILD_INFO.txt`
- `/work/input/patches/*.patch` (optional, zero or more)

Output: one ZIP under `/work/output/`.

Every patch in `input/patches/` is applied with `git apply` in name order, after
checkout and before `pio run`. Their presence is the only signal; the positional
argument contract is unchanged. The worker decides which patches a tag needs, so
the container applies what it was handed and nothing else — a patch subdirectory
rather than the input root, so the glob can never pick up `userPrefs.jsonc`.

A failed `git apply` exits 3 after printing
`MB_FAILURE code=patch_failed phase=patches detail=<patch file>`, so a build can
never compile without a change the user was promised.

## Reading A Build Log

The log is written to be scanned, not waded through. The container prints a
`##### phase: <name> #####` banner before checkout, patches, inputs, compile and
package; the worker wraps each Docker step in a `===== <step> =====` block; and a
failed build's stored log opens with the summary, so the first five lines say
what broke:

```
===== BUILD FAILED =====
code:   compile_error
phase:  compile
detail: src/mesh/NodeDB.cpp:705:27: error: 'info' was not declared in this scope
========================
```

Read one without opening SQLite by hand:

```bash
python3 -m meshtastic_builder build-log <public-token>
python3 -m meshtastic_builder build-log <public-token> --full
```

Build logs contain the full PlatformIO `-D` dump, which includes the WiFi PSK
and the MQTT password. They are never served over HTTP; this is a host-side
command only.

### Failure Codes

The worker classifies every failure into one of these, stored in
`build_requests.error_code`. The page translates the code; `error_message` holds
one quoted line of evidence, and only lines matching a diagnostic pattern are
ever lifted out of the log, so secrets in the flag dump cannot reach it.

| Code | Meaning |
| --- | --- |
| `patch_failed` | A required firmware patch did not apply; the build stopped before `pio run`. |
| `compile_error` | PlatformIO reported a compiler or linker error. |
| `firmware_too_big` | The image overflowed the device's flash or RAM region. |
| `no_artifacts` | The build finished but produced no firmware files. |
| `timeout` | A step exceeded its timeout. |
| `infrastructure` | Docker create/copy failed, or an input never reached the container. |
| `internal` | An unexpected worker exception; the log is the traceback. |
| `unknown` | Nothing in the log matched; the exit code is the only evidence. |

## ZIP Contents

The builder ZIP carries only what a flasher consumes, plus `FLASHING.txt` with
per-chip instructions, `BUILD_INFO.txt` with tag, SHA, device environment,
timestamp and source URL metadata, and the `userPrefs.jsonc` the firmware was
compiled against.

- ESP32: `firmware-*-update.bin` (app image alone, written at `0x10000`),
  `firmware-*.factory.bin` (bootloader + partition table + app, written at
  `0x0`), `littlefs-*.bin` for the spiffs partition, plus `bootloader.bin` and
  `partitions.bin` for flashing part by part.
- nRF52: `firmware-*.uf2` and `firmware-*.hex`. No factory image, no partition
  table and no filesystem image: those are ESP32 concepts.

Only `.elf` and `.map` are excluded (see `docker/build_firmware.sh`): they were
81% of the download and matter solely for decoding a backtrace.

### Why the App Image Is Named `-update.bin`

The [Meshtastic Web Flasher](https://flasher.meshtastic.org) only loads a release
manifest for firmware it hosts, so a ZIP the user picks themselves always takes
the web flasher's legacy path. That path searches the archive for
`firmware-<target>-<version>-update.bin` and explicitly excludes
`*.factory.bin`, so naming the app image that way is what lets the ZIP be
selected as-is instead of being unzipped first.

Its "erase and install" option cannot work with this ZIP on 2.8 firmware: it asks
for `bleota-s3.bin`, which upstream removed in 2.8. Use esptool for a full
install; `FLASHING.txt` in the ZIP carries the commands with this build's own
spiffs offset, read from its `partitions.bin`.

The upstream `bin/device-install.sh` is also unusable here, for a different
reason: it wants `firmware-*.mt.json`, which only `pio run -t mtjson` emits, and
`mt-<mcu>-ota.bin`, which upstream CI downloads from the separate
[meshtastic/esp32-unified-ota](https://github.com/meshtastic/esp32-unified-ota)
repository.

## Version Reproducibility

The API stores both:

- `firmware_tag`
- `firmware_sha`

The builder first tries to checkout the SHA and falls back to the tag. The ZIP includes metadata so the build can be audited later.
