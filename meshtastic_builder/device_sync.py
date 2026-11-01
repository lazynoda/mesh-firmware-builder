"""Regenerate data/devices.json from a firmware checkout.

The device list is read from the firmware's own variants/**/platformio.ini, so
it works the same for upstream and for forks with boards upstream lacks: every
env that, after resolving `extends` like PlatformIO, has
custom_meshtastic_display_name, custom_meshtastic_actively_supported = true and
no board_level = extra (see parse_boards for build variants and Meshtastic UI).
The Web Flasher's own list is hand-maintained in meshtastic/api and is not per
version, so the two differ by a few boards.

Run it against the checkout of the newest supported tag after each firmware
release. Existing entries keep their id and label (stored builds and shared
links reference the ids), new boards are appended, boards the firmware dropped
are removed. Nothing is written without --write.
"""

from __future__ import annotations

import configparser
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

from .devices import Device, load_devices


# They lead the list in this order, ahead of the alphabetical rest: the page
# preselects the first one, and these are the boards most builds are for.
LEAD_IDS = (
    "nrf52-promicro-diy",
    "tbeam",
    "heltec-v3",
    "heltec-v4",
    "heltec-mesh-node-t114",
    "tracker-t1000-e",
    "heltec-wsl-v3",
    "rak4631",
)

# Boards the flasher offers but this builder cannot ship yet. Each needs a
# reason. They stay out of every firmware's list, cached lists included.
EXCLUDED_ENVS: dict[str, str] = {}

# Whole chip families, so a fork's or a later tag's new board of that family is
# kept out too, not only the one board we happened to try.
EXCLUDED_FAMILIES: dict[str, str] = {
    # Compiles (with the native srec_cat), but ships only .hex files: no UF2,
    # no DFU zip, and FLASHING.txt would tell users to drag a UF2 onto it.
    "nrf54l15": "flashing nRF54L15 boards is not supported yet (issue #2)",
}


def exclusion_reason(env: str, family: str) -> str | None:
    return EXCLUDED_ENVS.get(env) or EXCLUDED_FAMILIES.get(family)

@dataclass(frozen=True)
class FlasherBoard:
    env: str
    label: str
    family: str
    source: str
    mui_env: str | None = None
    hybrid_env: str | None = None


# The Web Flasher's "Meshtastic UI" switch builds a board's `<env>-tft` env
# instead of `<env>`. See parse_boards() for which envs count as that variant.
MUI_SUFFIX = "-tft"

# Jentastic's hybrid builds: `<env>-hybrid` extends the board and compiles in
# JenCore and RNode. Offered as a switch on the board, like Meshtastic UI.
HYBRID_SUFFIX = "-hybrid"

# Env names reach `pio run -e` in the builder; the shell script enforces the same set.
SAFE_ENV_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")

# A hostile or broken repository must not turn one board list into an endless walk.
MAX_EXTENDS_STEPS = 64

_KEYS = (
    "custom_meshtastic_display_name",
    "custom_meshtastic_actively_supported",
    "custom_meshtastic_architecture",
    "custom_meshtastic_has_mui",
    "board_level",
)


def _multi_values(raw: str) -> list[str]:
    # platformio/project/config.py::parse_multi_values (PlatformIO 6.1.19)
    items = raw.split("\n" if "\n" in raw else ", ")
    return [item.strip() for item in items if item.strip()]


def _load_ini(files: Iterable[tuple[str, str]]) -> tuple[configparser.ConfigParser, dict[str, str]]:
    """All files in one parser, as PlatformIO reads platformio.ini plus extra_configs.

    Same parser settings as PlatformIO (`;` and `#` inline comments); no
    interpolation, because only plain keys are read. A file that does not parse
    is skipped rather than failing the whole list.
    """
    parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"), interpolation=None, strict=False)
    sources: dict[str, str] = {}
    for source, text in sorted(files):
        probe = configparser.ConfigParser(inline_comment_prefixes=("#", ";"), interpolation=None, strict=False)
        try:
            probe.read_string(text, source=source)
        except configparser.Error:
            continue
        parser.read_string(text, source=source)
        for section in probe.sections():
            sources.setdefault(section, source)
    return parser, sources


def _resolve(parser: configparser.ConfigParser, env: str) -> dict[str, tuple[str, str]]:
    """{key: (value, section it came from)} for one env, resolving `extends`.

    Mirrors ProjectConfig.walk_options: the env's own section first, then its
    `extends` chain (last listed first), then the global [env]; the first
    section that sets a key wins. That is what the firmware's own manifest
    generator reads through env.GetProjectOption().
    """
    found: dict[str, tuple[str, str]] = {}
    queue = ["env", f"env:{env}"]
    seen: set[str] = set()
    steps = 0
    while queue and steps < MAX_EXTENDS_STEPS:
        section = queue.pop()
        steps += 1
        if section in seen or not parser.has_section(section):
            continue
        seen.add(section)
        for key in _KEYS:
            if key not in found and parser.has_option(section, key):
                found[key] = (parser.get(section, key).strip(), section)
        if parser.has_option(section, "extends"):
            queue.extend(_multi_values(parser.get(section, "extends")))
    return found


def parse_boards(files: Iterable[tuple[str, str]]) -> dict[str, FlasherBoard]:
    """The boards to offer, from (path, platformio.ini text) pairs of one commit.

    An env is offered when, after resolving `extends` the way PlatformIO does,
    it has a display name, is actively supported and is not `board_level =
    extra`. Two kinds of env resolve to a board name without being boards:

    - an env that takes its display name from another offered env is a build
      variant of that board (`t-deck-tft` of `t-deck`, `rak4631_dbg` of
      `rak4631`), not a board of its own;
    - `<board>-tft` without a display name of its own is the board's Meshtastic
      UI build, offered as the board's switch (also when both take the name
      from a shared base section, as the ThinkNode M9 does).

    A `-tft` env whose base board is not offered (`seeed_wio_tracker_L2` is
    `extra`) is the board's only build, so it is offered as the board, like
    the Web Flasher does. A `-tft` env with a display name of its own (Heltec
    V4 TFT) stays a board of its own.

    `<board>-hybrid` (Jentastic) that takes its display name from the board
    and is not `extra` is the board's hybrid build, offered as a second switch.
    There is no flag on the board for it: the env existing is the signal.
    """
    parser, sources = _load_ini(files)
    envs = [s.removeprefix("env:") for s in parser.sections() if s.startswith("env:")]
    resolved = {env: _resolve(parser, env) for env in envs if SAFE_ENV_RE.match(env)}

    def value(env: str, key: str) -> str:
        return resolved[env].get(key, ("", ""))[0]

    def name_source(env: str) -> str:
        return resolved[env].get("custom_meshtastic_display_name", ("", ""))[1]

    def offered(env: str) -> bool:
        return (
            bool(value(env, "custom_meshtastic_display_name"))
            and value(env, "custom_meshtastic_actively_supported").lower() == "true"
            and value(env, "board_level").lower() != "extra"
        )

    def named_after_env(env: str) -> str | None:
        """The other env this one takes its display name from, if any."""
        source = name_source(env)
        if source.startswith("env:") and source != f"env:{env}":
            return source.removeprefix("env:")
        return None

    def mui_variant_of(env: str) -> str | None:
        """The board whose Meshtastic UI build this env is, if it is one."""
        if not env.endswith(MUI_SUFFIX) or name_source(env) == f"env:{env}":
            return None
        base = env[: -len(MUI_SUFFIX)]
        return base if base in resolved else None

    candidates = {env for env in resolved if offered(env)}
    boards: dict[str, FlasherBoard] = {}
    for env in sorted(candidates):
        base = mui_variant_of(env)
        if base is not None and base in candidates:
            continue  # the base board's switch, below
        parent = named_after_env(env)
        if parent is not None and parent in candidates and base is None:
            continue  # a build variant of another board (debug, InkHUD copy...)
        boards[env] = FlasherBoard(
            env=env,
            label=value(env, "custom_meshtastic_display_name")[:120],
            family=(value(env, "custom_meshtastic_architecture") or "unknown")[:40],
            source=sources.get(f"env:{env}", ""),
        )
    for env, board in list(boards.items()):
        mui_env = env + MUI_SUFFIX
        if (
            value(env, "custom_meshtastic_has_mui").lower() == "true"
            and mui_env in resolved
            and mui_env not in boards
            and mui_variant_of(mui_env) == env
            and value(mui_env, "board_level").lower() != "extra"
        ):
            boards[env] = replace(board, mui_env=mui_env)
        hybrid_env = env + HYBRID_SUFFIX
        if (
            hybrid_env in resolved
            and hybrid_env not in boards
            # Same name as the board, inherited (from the board env or a shared base).
            and name_source(hybrid_env) == name_source(env)
            and name_source(hybrid_env) != f"env:{hybrid_env}"
            and value(hybrid_env, "board_level").lower() != "extra"
        ):
            boards[env] = replace(boards[env], hybrid_env=hybrid_env)
    return boards


def flasher_boards(repo_path: Path) -> dict[str, FlasherBoard]:
    """parse_boards() over a local firmware checkout."""
    if not (repo_path / "variants").is_dir():
        raise ValueError(f"Not a Meshtastic firmware checkout (no variants/): {repo_path}")
    return parse_boards(
        (str(ini.relative_to(repo_path)), ini.read_text(encoding="utf-8", errors="ignore"))
        for ini in repo_path.glob("variants/**/platformio.ini")
    )


def device_id_for(env: str) -> str:
    """`seeed_wio_tracker_L1` -> `seeed-wio-tracker-l1`, the convention of the existing ids."""
    return re.sub(r"[^a-z0-9]+", "-", env.lower()).strip("-")


@dataclass
class DeviceSync:
    devices: list[Device]
    added: list[Device] = field(default_factory=list)
    removed: list[Device] = field(default_factory=list)
    family_changed: list[tuple[Device, str]] = field(default_factory=list)
    excluded: list[tuple[str, str]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed or self.family_changed)


def sync_devices(
    current: list[Device],
    boards: dict[str, FlasherBoard],
    *,
    strict: bool = True,
) -> DeviceSync:
    """Merge the firmware's boards onto `current`, keeping its ids and labels.

    strict=False is the runtime use (a per-firmware list built for the page):
    a board whose generated id collides with another env's id is skipped
    instead of stopping the whole list.
    """
    result = DeviceSync(devices=[])
    excluded = {
        env: reason
        for env, board in boards.items()
        if (reason := exclusion_reason(env, board.family)) is not None
    }
    result.excluded = sorted(excluded.items())
    wanted = {env: board for env, board in boards.items() if env not in excluded}

    kept: list[Device] = []
    for device in current:
        board = wanted.get(device.platformio_env)
        if board is None:
            result.removed.append(device)
            continue
        if board.family != device.family:
            result.family_changed.append((device, board.family))
        kept.append(
            Device(
                id=device.id,
                label=device.label,
                platformio_env=device.platformio_env,
                family=board.family,
                enabled=True,
                mui_env=board.mui_env,
                hybrid_env=board.hybrid_env,
            )
        )

    known_envs = {device.platformio_env for device in kept}
    used_ids = {device.id for device in kept}
    used_labels = {device.label for device in kept}
    for env in sorted(set(wanted) - known_envs):
        board = wanted[env]
        device_id = device_id_for(env)
        if device_id in used_ids:
            if not strict:
                continue
            raise ValueError(f"Generated id {device_id!r} for {env} is already taken; add it by hand.")
        label = board.label
        if label in used_labels:
            # Same rule as the existing entries: a shared display name gets a suffix.
            label = f"{label} ({env})"
        device = Device(
            id=device_id,
            label=label,
            platformio_env=env,
            family=board.family,
            enabled=True,
            mui_env=board.mui_env,
            hybrid_env=board.hybrid_env,
        )
        result.added.append(device)
        kept.append(device)
        used_ids.add(device_id)
        used_labels.add(label)

    lead = [device for lead_id in LEAD_IDS for device in kept if device.id == lead_id]
    rest = sorted((device for device in kept if device.id not in LEAD_IDS), key=lambda d: d.label.lower())
    result.devices = lead + rest
    return result


def devices_json(devices: list[Device]) -> str:
    payload = [
        {
            "id": device.id,
            "label": device.label,
            "platformio_env": device.platformio_env,
            "family": device.family,
            "enabled": device.enabled,
        }
        for device in devices
    ]
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def run_sync(root_dir: Path, repo_path: Path, *, write: bool) -> DeviceSync:
    result = sync_devices(load_devices(root_dir), flasher_boards(repo_path))
    for device in result.added:
        print(f"ADD\t{device.id}\t{device.platformio_env}\t{device.family}\t{device.label}")
    for device in result.removed:
        print(f"REMOVE\t{device.id}\t{device.platformio_env}\t{device.label}")
    for device, family in result.family_changed:
        print(f"FAMILY\t{device.id}\t{device.family} -> {family}")
    for env, reason in result.excluded:
        print(f"SKIP\t{env}\t{reason}")
    print(f"{len(result.devices)} devices ({len(result.added)} added, {len(result.removed)} removed).")
    if write and result.changed:
        (root_dir / "data" / "devices.json").write_text(devices_json(result.devices), encoding="utf-8")
        print("Wrote data/devices.json.")
    elif result.changed:
        print("Dry run: pass --write to update data/devices.json.")
    return result
