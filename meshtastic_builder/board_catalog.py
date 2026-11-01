"""The boards each firmware version offers, read from its own repository.

Each firmware (and each version of it) has its own variants/**/platformio.ini,
and forks add boards upstream does not have. The list for one commit is read
from GitHub once and stored in SQLite: two API calls for the variants tree,
then the platformio.ini files from raw.githubusercontent.com, cached on disk
by blob SHA so a new tag only downloads the files that changed.

Ids and labels already in data/devices.json are kept, because stored builds
and shared links reference them; boards new to that file get an id from their
env name. When GitHub cannot be reached and nothing is cached, the page falls
back to data/devices.json.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from typing import Any

from .config import Config
from .db import connection, initialize_database, iso_now
from .device_sync import exclusion_reason, parse_boards, sync_devices
from .devices import Device, enabled_devices
from .firmwares import FirmwareSource

# Server-side wording for API clients; the page translates the code itself.
UNAVAILABLE_REASONS = {
    "firmware_too_big": "el firmware no cabe en la memoria flash de esta placa",
}

# Upper bounds on what one commit may make us download. Upstream has ~200
# platformio.ini files under variants/; these leave room without letting a
# hostile repository listed by mistake turn one page load into thousands.
MAX_INI_FILES = 600
MAX_INI_BYTES = 256 * 1024
FETCH_WORKERS = 8

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# Bumped whenever the list read from platformio.ini changes (a new Device field,
# a new parsing rule), so lists cached by an older version are read again once.
# 2: Meshtastic UI. 3: keys inherited through `extends`. 4: hybrid builds.
CATALOG_FORMAT = 4
_locks: dict[tuple[str, str], threading.Lock] = {}
_locks_guard = threading.Lock()


class BoardCatalogError(RuntimeError):
    pass


def _lock_for(key: tuple[str, str]) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _http_get(url: str) -> str:
    # Imported here so tests can patch firmware._http_get once for everything.
    from . import firmware

    body, _headers = firmware._http_get(url, timeout=20)
    return body


def _variants_tree(source: FirmwareSource, sha: str) -> list[dict[str, Any]]:
    root = json.loads(_http_get(f"https://api.github.com/repos/{source.full_name}/git/trees/{sha}"))
    variants = next((item for item in root.get("tree", []) if item.get("path") == "variants"), None)
    if variants is None:
        raise BoardCatalogError(f"{source.name} has no variants/ directory at {sha[:7]}.")
    tree = json.loads(
        _http_get(f"https://api.github.com/repos/{source.full_name}/git/trees/{variants['sha']}?recursive=1")
    )
    if tree.get("truncated"):
        raise BoardCatalogError(f"GitHub truncated the variants tree of {source.name}.")
    files = [
        item
        for item in tree.get("tree", [])
        if item.get("type") == "blob" and str(item.get("path", "")).endswith("platformio.ini")
    ]
    if len(files) > MAX_INI_FILES:
        raise BoardCatalogError(f"{source.name} has {len(files)} platformio.ini files, over the limit.")
    return files


def _read_ini(config: Config, source: FirmwareSource, sha: str, item: dict[str, Any]) -> tuple[str, str]:
    path = f"variants/{item['path']}"
    blob = str(item.get("sha", ""))
    cache = config.cache_dir / "variant-ini" / f"{blob}.ini" if _SHA_RE.match(blob) else None
    if cache is not None and cache.exists():
        return path, cache.read_text(encoding="utf-8")
    if int(item.get("size") or 0) > MAX_INI_BYTES:
        return path, ""
    text = _http_get(f"https://raw.githubusercontent.com/{source.full_name}/{sha}/{path}")
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
    return path, text


def fetch_board_devices(config: Config, source: FirmwareSource, sha: str) -> list[Device]:
    """The page's device list for one commit of one firmware."""
    if not _SHA_RE.match(sha):
        raise BoardCatalogError(f"Not a commit SHA: {sha!r}")
    files = _variants_tree(source, sha)
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        texts = list(pool.map(lambda item: _read_ini(config, source, sha, item), files))
    boards = parse_boards(texts)
    if not boards:
        raise BoardCatalogError(f"No flashable boards found in {source.name} at {sha[:7]}.")
    return sync_devices(enabled_devices(config.root_dir), boards, strict=False).devices


def _load_cached(config: Config, firmware_id: str, sha: str) -> list[Device] | None:
    with connection(config) as conn:
        row = conn.execute(
            "SELECT devices_json FROM board_catalogs WHERE firmware_id = ? AND sha = ?",
            (firmware_id, sha),
        ).fetchone()
    if row is None:
        return None
    stored = json.loads(row["devices_json"])
    if not isinstance(stored, dict) or stored.get("format") != CATALOG_FORMAT:
        return None
    return [Device(**item) for item in stored["devices"]]


def _store(config: Config, firmware_id: str, sha: str, devices: list[Device]) -> None:
    payload = json.dumps({"format": CATALOG_FORMAT, "devices": [asdict(device) for device in devices]})
    with connection(config) as conn:
        conn.execute(
            """
            INSERT INTO board_catalogs (firmware_id, sha, devices_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(firmware_id, sha) DO UPDATE SET
              devices_json = excluded.devices_json,
              created_at = excluded.created_at
            """,
            (firmware_id, sha, payload, iso_now()),
        )


def devices_for(config: Config, source: FirmwareSource, sha: str) -> tuple[list[Device], bool]:
    """(devices, from_firmware). from_firmware is False when this is the static fallback.

    Exclusions are applied on every read, so excluding a board takes effect on
    lists cached before the exclusion existed.
    """
    devices, from_firmware = _devices_for(config, source, sha)
    return [d for d in devices if exclusion_reason(d.platformio_env, d.family) is None], from_firmware


def _devices_for(config: Config, source: FirmwareSource, sha: str) -> tuple[list[Device], bool]:
    initialize_database(config)
    cached = _load_cached(config, source.id, sha)
    if cached is not None:
        return cached, True
    with _lock_for((source.id, sha)):
        cached = _load_cached(config, source.id, sha)
        if cached is not None:
            return cached, True
        try:
            devices = fetch_board_devices(config, source, sha)
        except (urllib.error.URLError, TimeoutError, BoardCatalogError, json.JSONDecodeError, KeyError) as exc:
            print(f"Board list for {source.id}@{sha[:7]} unavailable, using data/devices.json: {exc}")
            return enabled_devices(config.root_dir), False
        _store(config, source.id, sha, devices)
        return devices, True


def get_device_for_build(
    config: Config,
    source: FirmwareSource,
    sha: str,
    device_id: str,
    *,
    mui: bool = False,
    hybrid: bool = False,
    version: str | None = None,
) -> Device:
    """The board to build. With `mui`, its Meshtastic UI env; with `hybrid`, its
    JenCore + RNode env. Each labelled as such; never both (no env is both).

    `version` is the x.y.z being built: a board can be unavailable on some
    versions of a firmware and fine on later ones."""
    devices, _from_firmware = devices_for(config, source, sha)
    for device in devices:
        if device.id == device_id:
            if mui and hybrid:
                raise ValueError("Meshtastic UI y la variante hibrida no se pueden combinar.")
            if mui:
                if not device.mui_env:
                    raise ValueError(f"{device.label} no tiene Meshtastic UI en esta version de {source.name}.")
                device = replace(device, platformio_env=device.mui_env, label=f"{device.label} (Meshtastic UI)")
            if hybrid:
                if not device.hybrid_env:
                    raise ValueError(f"{device.label} no tiene variante hibrida en esta version de {source.name}.")
                device = replace(device, platformio_env=device.hybrid_env, label=f"{device.label} (JenCore + RNode)")
            unavailable = source.unavailable(device.platformio_env, version)
            if unavailable is not None:
                # Listed, so users can read why, but never queued: it cannot succeed.
                where = f"con {source.name} {version}" if version else f"con {source.name} por ahora"
                fixed = (
                    f" Funciona a partir de la version {unavailable.fixed_since}."
                    if unavailable.fixed_since
                    else ""
                )
                raise ValueError(
                    f"{device.label} no esta disponible {where} "
                    f"({UNAVAILABLE_REASONS.get(unavailable.reason, unavailable.reason)}).{fixed} "
                    f"Se esta trabajando en ello: {unavailable.issue}"
                )
            return device
    raise ValueError("Dispositivo no soportado por este firmware.")
