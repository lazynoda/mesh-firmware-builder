# Meshtastic Builder

[![CI](https://github.com/lazynoda/meshtastic-builder/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/lazynoda/meshtastic-builder/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/lazynoda/meshtastic-builder)](https://github.com/lazynoda/meshtastic-builder/releases/latest)
[![License](https://img.shields.io/github/license/lazynoda/meshtastic-builder)](LICENSE)
[![Website](https://img.shields.io/website?url=https%3A%2F%2Fbuilder.meshtastic.lazynoda.es%2Fapi%2Fhealth)](https://builder.meshtastic.lazynoda.es)
[![Firmwares built](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbuilder.meshtastic.lazynoda.es%2Fapi%2Fhealth&query=%24.builds.succeeded&label=firmwares%20built)](https://builder.meshtastic.lazynoda.es)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-lazynoda-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/lazynoda)

Custom [Meshtastic](https://meshtastic.org) firmware, built with your settings
already inside.

Stock firmware boots with no region, no names, no channels and default
security, and you configure it afterwards over Bluetooth or USB. Meshtastic
Builder compiles those settings into the firmware instead: pick a device and a
firmware version, fill in a form, and download a ZIP ready to flash.

**Public instance:** <https://builder.meshtastic.lazynoda.es>

- No account and no email. Each build gets a private link, and its ZIP stays
  downloadable for 7 days.
- Official firmware from [meshtastic/firmware](https://github.com/meshtastic/firmware),
  or one of the community firmwares listed in
  [`data/firmwares.json`](docs/firmwares.md), compiled with PlatformIO. Only two
  small, documented patches are ever applied;
  see [Advanced Build Options](docs/build-options.md#the-two-patches).
- Every board each firmware version declares as supported in its own
  `platformio.ini` files (105 for Meshtastic 2.8.1), close to what the
  [Meshtastic Web Flasher](https://flasher.meshtastic.org) offers, with its
  Meshtastic UI builds for boards like the T-Deck.
- Interface in Spanish and English.

## What You Can Set

- Node long and short name, timezone.
- LoRa region, modem preset, TX power, and manual LoRa parameters (bandwidth,
  spreading factor, coding rate, frequency).
- Device role, rebroadcast mode, node info and telemetry intervals.
- Up to 8 channels with name, PSK, position precision and mute.
- Bluetooth PIN, WiFi, MQTT broker and credentials.
- Position: GPS mode, broadcast interval, smart position, fixed position.
- Admin keys, managed mode, packet signature policy.
- Any other key in the firmware's `userPrefs.jsonc`.

The full list, with what the firmware accepts and why some settings are
rejected, is in [userPrefs Support](docs/userprefs-support.md).

## Flashing the ZIP

Every ZIP carries a `FLASHING.txt` with the exact steps for its chip.

- **nRF52** (Pro-micro DIY, Heltec T114, RAK4631…): double-tap reset and copy
  the `.uf2` file onto the USB drive that appears.
- **ESP32** (Heltec V4, T-Beam, Station G2…): open the
  [Meshtastic Web Flasher](https://flasher.meshtastic.org), pick your device,
  choose the custom firmware option and select the ZIP as is. Its
  *erase and install* option does not work with custom ZIPs on firmware 2.8
  (it asks for `bleota-s3.bin`, which upstream removed), so use `esptool` for a
  full install; `FLASHING.txt` has the commands.

Most settings are applied on first boot and after a factory reset. A node that
is already configured keeps its current settings until it is reset.

Why the files are named the way they are is explained in
[Worker and Builder](docs/worker-and-builder.md#zip-contents).

## Running Your Own Instance

Requirements: Docker with the Compose plugin, about 12 GB of disk for the
firmware builder image, and room for the compiler cache (capped at 20 GB by
default, `MB_CCACHE_MAXSIZE`). The first build of a board and version takes
roughly 7 to 26 minutes at 1 CPU, depending on the chip; later builds of the
same board and version reuse the cache and take a few minutes.

```bash
git clone https://github.com/lazynoda/meshtastic-builder.git
cd meshtastic-builder
cp .env.example .env    # set MB_BASE_URL to your public URL

# One-off, about an hour: clones the firmware and prewarms the toolchains.
docker build -f docker/builder.Dockerfile -t meshtastic-firmware-builder:local .

docker compose -f compose.yml up -d --build
```

With rootless Docker, also set `MB_DOCKER_SOCKET=/run/user/<uid>/docker.sock` in
`.env`.

Then:

- [Operations](docs/operations.md): reverse proxy, TLS, backups, firmware
  version admin.
- [Docker Compose Flow](docs/compose-flow.md): a step-by-step smoke test,
  including a fake mode that tests the whole flow without compiling anything.
- [Configuration](docs/configuration.md): every `MB_*` variable.

## How It Works

A small Python web app (standard library only, SQLite, no frontend build step)
stores each request in a queue. A worker picks requests one at a time and
compiles each one in a throwaway Docker container with PlatformIO. The web
process never touches Docker.

```text
browser ──> web (validate, queue) ──> SQLite <── worker ──> builder container
                                                    │          (PlatformIO)
                                                    └──> ZIP, kept 7 days
```

Everything the user sends is validated against the selected firmware version
before it reaches the compiler, because each setting becomes a `-D` compiler
flag. See [Security Model](docs/security.md).

## Documentation

All documentation is in [docs/](docs/README.md): architecture, API, worker and
builder image, frontend, database, security and testing.

Working on the code with an AI agent? Read [AGENTS.md](AGENTS.md) first.

## Development

```bash
cp .env.example .env
python3 -m meshtastic_builder.db
python3 -m meshtastic_builder.app                            # http://localhost:8080
MB_BUILDER_MODE=fake python3 -m meshtastic_builder.worker    # no Docker needed
python3 -B -m unittest discover -s tests
```

Details in [Local Development](docs/local-development.md).

## License

AGPL-3.0-only, see [LICENSE](LICENSE). If you run a modified version of this
service for others over a network, you must offer them its source code.

The patches in `docker/patches/` modify the Meshtastic firmware and stay under
its license, GPL-3.0. GPL-3.0 section 13 allows combining them with this
AGPL-3.0 project.

Meshtastic is a registered trademark of Meshtastic LLC. This project is not
affiliated with or endorsed by Meshtastic LLC.
