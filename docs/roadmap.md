# Roadmap

## Implemented

- Web form for device, firmware tag, and generated `userPrefs.jsonc` preferences.
- SQLite-backed request queue.
- Random public tokens for status/download URLs.
- GitHub tag sync with pagination.
- Admin commands to refresh, list, support, and unsupport firmware versions.
- Admin command to validate allowlisted devices against a local Meshtastic firmware checkout.
- Admin command to check Docker daemon reachability before real builds.
- Tag-specific `userPrefs.jsonc` template fetch/cache.
- Submitted `userPrefs.jsonc` overrides are merged onto the selected tag template.
- UI controls for common preferences: owner names, LoRa region, allowed role, preset, TX power, channels (8 from 2.8.0, with per-channel mute), node behaviour and telemetry intervals, MQTT broker plus credentials and root topic, POSIX TZ string, three admin keys, managed mode, and packet signature policy.
- Firmware-version gating of protobuf enum values in the UI.
- Worker process.
- Fake builder mode for fast local testing.
- Docker builder image for Meshtastic firmware.
- Builds against a remote Docker daemon (`DOCKER_HOST=ssh://...`).
- ZIP artifact storage.
- Compiler cache (ccache) shared by builds, in a Docker named volume with a size cap.
- Private build URL returned at submit time; no email is requested or sent.
- 7-day artifact expiry.
- Unit tests for core contracts.
- Advanced build options (`ok_to_mqtt`, manual LoRa config): native on firmware
  2.8.0 and newer, and through a repo-controlled firmware patch below it.
- Value hardening so no preference can inject extra compiler flags.
- Frontend restyled on the shared [meshtastic.es](https://meshtastic.es) design system, with Spanish and
  English UI and shareable `/?build=<token>` links.
- Reverse-proxy readiness (`MB_TRUST_PROXY`) and a sample Caddyfile.

## Next Milestones

1. Add automated smoke-test status for supported firmware tags and devices,
   including `git apply --check` of every `docker/patches/*.patch` per tag.
2. Generate preference UI controls from a maintained schema.
3. Add persistent rate limiting.
4. Add production object storage support.
5. Add Postgres backend if queue concurrency or deployment scale requires it.
