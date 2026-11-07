# Operations

## Start

Local:

```bash
python3 -m meshtastic_builder.app
python3 -m meshtastic_builder.worker
```

Compose:

```bash
docker compose -f compose.yml up --build
```

For a step-by-step Compose smoke test, including fake mode, real firmware
builds and remote Docker, see [Docker Compose Flow](compose-flow.md).

## Logs

The current implementation logs to stdout.

Worker logs include:

- worker id,
- claimed token,
- platformio env,
- firmware tag,
- success/failure state.

A failed build prints one triage line:

```
Build <token> FAILED [compile_error/compile] nrf52_promicro_diy_tcxo at v2.8.0.47db0e3: src/mesh/NodeDB.cpp:705:27: error: ...
```

Build logs are truncated and stored in `build_requests.build_log`, newest 20 KB,
with the failure summary at the top. Read one with
`python3 -m meshtastic_builder build-log <token>`. See
[Worker And Builder](worker-and-builder.md) for the phase banners and the failure
codes.

## Cleanup

Run manually:

```bash
python3 -m meshtastic_builder.cleanup
```

The worker also runs cleanup periodically.

## Compiler Cache

Builds share a ccache cache in the Docker volume named by `MB_CCACHE_VOLUME`
(`meshtastic-builder-ccache` in Compose); see
[Worker And Builder](worker-and-builder.md#compiler-cache-ccache). ccache keeps it
under `MB_CCACHE_MAXSIZE` on its own. To read its size and hit rate, or to
empty it (the next build of each board then compiles everything once):

```bash
docker run --rm -v meshtastic-builder-ccache:/ccache -e CCACHE_DIR=/ccache \
  --entrypoint ccache meshtastic-firmware-builder:local --show-stats
# empty it, with no build running:
docker volume rm meshtastic-builder-ccache
```

A Compose project prefixes nothing here: the worker passes the name to the
daemon as is, so dev and prod instances on one host share the cache unless one
sets another name. Sharing is safe: ccache reuses an object only when the
compiler, flags and preprocessed source are identical.

## Shared Package Downloads

PlatformIO's downloaded archives live in the Docker volume named by
`MB_PIO_DOWNLOAD_VOLUME` (`meshtastic-builder-pio-downloads` in Compose); see
[Worker And Builder](worker-and-builder.md#shared-package-downloads). Dev and
prod instances can share it too: archives are filed by URL and checksum. To see
its size, or to empty it with no build running:

```bash
docker run --rm -v meshtastic-builder-pio-downloads:/d --entrypoint du \
  meshtastic-firmware-builder:local -sh /d
docker volume rm meshtastic-builder-pio-downloads
```

## Firmware Version Admin

The page has no refresh button: it only reads what is cached, and fetches from
GitHub on its own only when a firmware has no cached tags yet. New releases
appear after an operator refresh. Run it by hand or from a daily cron on the
host:

```bash
python3 -m meshtastic_builder refresh-versions                       # every firmware
python3 -m meshtastic_builder refresh-versions --firmware jentastic  # just one
# from the host, against the running container:
docker compose exec -T web python -m meshtastic_builder refresh-versions
```

It refreshes the tags of every firmware in `data/firmwares.json` (and the head
of branch firmwares), and exits 1 if any firmware failed. The board list of a
new tag is read from GitHub the first time someone selects that tag, so it
needs no separate step. Branch heads also refresh on their own every five
minutes. `GET /api/firmware-versions?firmware=<id>&refresh=1` does the same for
one firmware over HTTP.

List supported versions:

```bash
python3 -m meshtastic_builder list-versions
```

List all cached versions, including unsupported:

```bash
python3 -m meshtastic_builder list-versions --all
```

Mark a tag supported or unsupported:

```bash
python3 -m meshtastic_builder set-supported v2.7.25.104df5f
python3 -m meshtastic_builder set-unsupported v2.7.25.104df5f
```

Validate enabled devices against a local checkout of
[meshtastic/firmware](https://github.com/meshtastic/firmware):

```bash
python3 -m meshtastic_builder validate-devices /path/to/meshtastic/firmware
```

This checks `variants/**` files, not only the root `platformio.ini`.

Check whether Docker is reachable before attempting a real build:

```bash
python3 -m meshtastic_builder docker-status --timeout-seconds 10
```

If this command times out or fails, do not start a firmware build. Fix the Docker context or daemon first.

## Backups

Back up:

- SQLite database,
- `.env` and the reverse proxy config.

The database is the only record of a build: its token is what the user holds.

Artifacts are not worth backing up: they expire after `MB_ARTIFACT_TTL_DAYS` and
are reproducible from `firmware_sha` plus the stored `prefs_jsonc`.

Do not back up temporary job directories.

A WAL-safe daily backup is one line in cron:

```bash
0 4 * * * sqlite3 /srv/meshtastic-builder/data/meshtastic-builder.sqlite \
  ".backup /srv/backups/mb-$(date +\%F).sqlite" \
  && find /srv/backups -name 'mb-*.sqlite' -mtime +14 -delete
```

## Deployment

The service runs behind a TLS-terminating reverse proxy. `Caddyfile.example`
in the repo root is a working starting point:

```caddyfile
builder.example.org {
    reverse_proxy web:8080
}
```

Checklist for a fresh host:

1. Point DNS at the host and open ports 80/443 for the proxy only.
2. Set `MB_BASE_URL=https://builder.example.org` and `MB_TRUST_PROXY=1` in `.env`,
   or start from `docker-compose.example.yaml`, which spells the same settings out
   inline with the reasoning for each one.
   Enable `MB_TRUST_PROXY` only when the app port is not reachable directly, as
   `X-Forwarded-For` is otherwise trivially spoofed.
3. Stop publishing the `web` port to the public interface; let the proxy reach it
   over the compose network.
4. Build the firmware builder image on the host and pin it via `MB_BUILDER_IMAGE`.
   With rootless Docker, set `MB_DOCKER_SOCKET=/run/user/<uid>/docker.sock`.
5. Run one real build end to end before announcing the service.

Services already carry `restart: unless-stopped`, so Docker restores the stack on
reboot. No systemd units are needed.

## Concurrency

The service ships configured for one build at a time. The queue claim is already
transactional and builder containers are ephemeral, so scaling is purely
operational:

```bash
docker compose up -d --scale worker=2
```

Budget roughly `MB_DOCKER_CPUS` cores per worker: at the default of 4, two
workers want about 8 cores. No code change is required.

## Production Notes

- Set `MB_BASE_URL` to the public HTTPS origin.
- Build and pin a known-good builder image.
- Decide which firmware tags are supported.
- Re-verify `docker/patches/*.patch` when widening the supported tag
  range. See [Advanced Build Options](build-options.md).
- Run at least one real Docker build smoke test before accepting users.
- Consider moving from SQLite to Postgres if multiple web instances are needed.
