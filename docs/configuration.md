# Configuration

Configuration is read from environment variables.

## Core

| Variable | Default | Description |
| --- | --- | --- |
| `MB_BASE_URL` | `http://localhost:8080` | Public base URL used in the build/status/download links returned at submit time. |
| `MB_HOST` | `127.0.0.1` | HTTP bind host. |
| `MB_PORT` | `8080` | HTTP bind port. |
| `MB_TRUST_PROXY` | `0` | Trust the first `X-Forwarded-For` hop for rate limiting. Enable only when the app is reachable exclusively through a reverse proxy, otherwise clients can spoof the header. |
| `MB_DATA_DIR` | `./var` | Runtime data root. |
| `MB_DB_PATH` | `./var/meshtastic-builder.sqlite` | SQLite database path. |
| `MB_ARTIFACT_DIR` | `./var/artifacts` | ZIP artifact directory. |
| `MB_JOB_DIR` | `./var/jobs` | Temporary per-build job directory. |
| `MB_CACHE_DIR` | `./var/cache` | Cache directory for firmware metadata/templates. |

## Firmware Metadata

| Variable | Default | Description |
| --- | --- | --- |
| `MB_GITHUB_TAGS_URL` | GitHub tags API for [meshtastic/firmware](https://github.com/meshtastic/firmware) | Tag source URL for the `meshtastic` firmware only. Other firmwares use their own repository from [`data/firmwares.json`](firmwares.md). |
| `MB_GITHUB_MAX_TAG_PAGES` | `20` | Maximum GitHub tag pages to follow. |
| `MB_AUTO_SUPPORT_LATEST_TAGS` | `20` | Number of newest tags to mark supported on first cache insert. Set `0` to auto-support all new tags. |
| `MB_RAW_USERPREFS_URL` | Raw GitHub URL template | Source for tag-specific `userPrefs.jsonc` of the `meshtastic` firmware. |

## Builder

| Variable | Default | Description |
| --- | --- | --- |
| `MB_BUILDER_MODE` | `docker` | `docker` or `fake`. |
| `MB_BUILDER_IMAGE` | `meshtastic-firmware-builder:local` | Docker image used by the worker. |
| `MB_DOCKER_BINARY` | `docker` | Docker CLI executable. |
| `MB_DOCKER_NETWORK` | `bridge` | Network mode for builder containers. Use `none` only with images prewarmed for the target tag/device set. |
| `MB_DOCKER_TRANSPORT` | `auto` | `auto`, `bind`, or `copy`. `auto` uses `copy` for remote `DOCKER_HOST` values such as `ssh://...` and for a worker running inside a container, and `bind` otherwise. |
| `MB_DOCKER_CPUS` | `4` | CPU quota for firmware builder containers. T114/nRF52 builds are CPU-bound, so this default keeps a limit while avoiding the previous 2-CPU bottleneck. |
| `MB_DOCKER_MEMORY` | `4g` | Memory limit for firmware builder containers. |
| `MB_DOCKER_PIDS_LIMIT` | `512` | PID limit for firmware builder containers. |
| `MB_BUILD_TIMEOUT_SECONDS` | `3600` | Per-build timeout. |
| `MB_CCACHE_VOLUME` | empty (`meshtastic-builder-ccache` in Compose) | Docker named volume mounted into every builder container as its [ccache](worker-and-builder.md#compiler-cache-ccache) directory. A name, never a host path. Empty turns the compiler cache off; an invalid name also turns it off instead of failing builds. |
| `MB_CCACHE_MAXSIZE` | `20G` | Size cap ccache keeps the cache under, dropping the least recently used objects first. ccache syntax: a number with an optional `k`/`M`/`G`/`T` suffix (`Ki`/`Mi`/`Gi`/`Ti` for powers of two). An invalid value turns the cache off. |
| `MB_DOCKER_SOCKET` | `/var/run/docker.sock` | Compose only: host path of the Docker socket mounted into the worker. Rootless Docker uses `/run/user/<uid>/docker.sock`. |
| `MB_STALE_RUNNING_SECONDS` | `7200` | Running jobs older than this are requeued. |
| `MB_ARTIFACT_TTL_DAYS` | `7` | Download availability after successful build. |

## Validation

| Variable | Default | Description |
| --- | --- | --- |
| `MB_MAX_PREFS_BYTES` | `65536` | Maximum submitted `userPrefs.jsonc` size. |

## Advanced Build Options

Options that `userPrefs.jsonc` cannot express are allowlisted in
`data/build_options.json`, not in environment variables. See
[Advanced Build Options](build-options.md).

## Supported Devices

Supported devices are allowlisted in `data/devices.json`.

`data/devices.json` lists 96 devices, derived from the firmware's own variant
metadata (see [AGENTS.md](../AGENTS.md#devices) for the selection rule). Each entry maps a stable `id` to
the `platformio_env` the worker builds and a `family` used to hide settings a
board cannot have, such as WiFi on nRF52.

The list does not follow new firmware releases by itself. After each release,
regenerate it from a checkout of the newest supported tag:

```bash
git -C /path/to/meshtastic/firmware checkout <newest-tag>
python3 -m meshtastic_builder sync-devices /path/to/meshtastic/firmware          # dry run
python3 -m meshtastic_builder sync-devices /path/to/meshtastic/firmware --write
```

It prints one line per added (`ADD`), dropped (`REMOVE`) or re-familied
(`FAMILY`) board. Existing entries keep their `id` and label, new boards are
appended in alphabetical order, and a board the firmware no longer offers is
removed. The builder image already holds a full firmware clone, so the check
needs no extra download:

```bash
docker run --rm --network none --entrypoint sh -v "$PWD:/app" meshtastic-firmware-builder:local \
  -c 'cd /opt/firmware && git checkout -q --force <newest-tag> && cd /app && python3 -m meshtastic_builder sync-devices /opt/firmware'
```

Validate the allowlist against a Meshtastic firmware checkout after changing it:

```bash
python3 -m meshtastic_builder validate-devices /path/to/meshtastic/firmware
```

The page does not show this file as is. For each firmware and version it
reads the boards from that commit's own `variants/**/platformio.ini` (see
[Firmware Sources](firmwares.md#boards)), so forks show their own boards and
older tags only offer the boards they had. This file supplies the ids and
labels of known boards, and is the fallback list when GitHub cannot be
reached.

## Notifications

There are none. The service never asks for an email address and never sends one.
A submitted build is addressable only through the private URL returned by
`POST /api/builds`.
