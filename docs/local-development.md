# Local Development

## Requirements

Minimum:

- Python 3.11+
- SQLite

For real firmware builds:

- Docker
- Docker Compose plugin if using `compose.yml`

For local fake builds, Docker is not required.

## Run the Web App

```bash
cp .env.example .env
python3 -m meshtastic_builder.db
python3 -m meshtastic_builder.app
```

Open:

```text
http://localhost:8080
```

## Frontend Changes

The frontend has no build step. Edit files under `static/` and reload the page.
See [Frontend](frontend.md) for the layout, styling rules, and how the
Spanish/English dictionary works.

Rebuilding the firmware builder image is only needed when
`docker/build_firmware.sh`, `docker/prewarm.sh` or the Dockerfile change; the
patches are copied into the job input at build time from the repo, so editing
anything under `docker/patches/` needs no image rebuild. The entrypoint fetches
tags before checkout, so an existing image can still build firmware tags
released after it.

A `docker/build_firmware.sh` rebuild is cheap: it is copied in after the prewarm
layer, so only the last two layers are redone. A `docker/prewarm.sh` or
Dockerfile change re-prewarms, which is the hour-long one.

## Run the Worker

Real Docker builder mode:

```bash
python3 -m meshtastic_builder.worker
```

Fake mode for local flow testing:

```bash
MB_BUILDER_MODE=fake python3 -m meshtastic_builder.worker
```

Process at most one job:

```bash
MB_BUILDER_MODE=fake python3 -m meshtastic_builder.worker --once
```

## Build the Firmware Builder Image

```bash
docker build -f docker/builder.Dockerfile -t meshtastic-firmware-builder:local .
```

The image clones [meshtastic/firmware](https://github.com/meshtastic/firmware), installs PlatformIO, fetches tags, and prewarms dependencies for the configured environments.

## Docker Compose

Fast end-to-end test without compiling firmware:

```bash
MB_BUILDER_MODE=fake docker compose -f compose.yml up --build
```

Real firmware build flow:

```bash
docker build -f docker/builder.Dockerfile -t meshtastic-firmware-builder:local .
MB_BUILDER_MODE=docker docker compose -f compose.yml up --build
```

For the full checklist, including remote Docker and API-based submission, see
[Docker Compose Flow](compose-flow.md).

The worker service mounts the host Docker socket (`MB_DOCKER_SOCKET`, default `/var/run/docker.sock`; rootless Docker uses `/run/user/<uid>/docker.sock`) so it can create ephemeral builder containers. The web service does not need Docker socket access.

## tmux

If you want persistent local processes during development:

```bash
tmux new -s mesh-firmware-builder
```

Suggested panes:

```bash
python3 -m meshtastic_builder.app
MB_BUILDER_MODE=fake python3 -m meshtastic_builder.worker
```

Kill the session when done:

```bash
tmux kill-session -t mesh-firmware-builder
```
