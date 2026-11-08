"""The boards each firmware version offers, read from its own repository.

Each firmware (and each version of it) has its own variants/**/platformio.ini,
and forks add boards upstream does not have. The list for one commit is read
from GitHub once and stored in SQLite: two API calls for the variants tree,
then the platformio.ini files from raw.githubusercontent.com, cached on disk
by blob SHA so a new tag only downloads the files that changed.

The same row also records which PlatformIO Core builds each board (see
platformio_versions.py): that needs the root platformio.ini and every file its
`extra_configs` loads, plus one platform.json per distinct platform.

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
from .platformio_versions import (
    UNSUPPORTED,
    PlatformLookupError,
    extra_config_paths,
    extra_config_patterns,
    is_glob,
    load_project,
    platformio_for_envs,
)

# Server-side wording for API clients; the page translates the code itself.
UNAVAILABLE_REASONS = {
    "firmware_too_big": "el firmware no cabe en la memoria flash de esta placa",
    "platformio_unsupported": "esta version necesita una version de PlatformIO que el compilador aun no tiene",
}
# Shown with a platformio_unsupported board. No firmware has needed it yet, so
# there is no specific issue to point at; the fix is adding that Core to the image.
PLATFORMIO_UNSUPPORTED_ISSUE = "https://github.com/lazynoda/meshtastic-builder/issues"

# Upper bounds on what one commit may make us download. Upstream has ~200
# platformio.ini files under variants/ and ~220 ini files loaded in total;
# these leave room without letting a hostile repository listed by mistake turn
# one page load into thousands.
MAX_INI_FILES = 600
MAX_INI_BYTES = 256 * 1024
FETCH_WORKERS = 8

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# Bumped whenever the list read from platformio.ini changes (a new Device field,
# a new parsing rule), so lists cached by an older version are read again once.
# 2: Meshtastic UI. 3: keys inherited through `extends`. 4: hybrid builds.
# 5: the PlatformIO Core each env builds with.
CATALOG_FORMAT = 5
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


def _root_tree(source: FirmwareSource, sha: str) -> list[dict[str, Any]]:
    root = json.loads(_http_get(f"https://api.github.com/repos/{source.full_name}/git/trees/{sha}"))
    return list(root.get("tree", []))


def _subtree_ini_files(source: FirmwareSource, root: list[dict[str, Any]], top: str) -> list[dict[str, Any]]:
    """Every .ini under a top-level directory, with paths from the repository root."""
    entry = next((item for item in root if item.get("path") == top and item.get("type") == "tree"), None)
    if entry is None:
        return []
    tree = json.loads(
        _http_get(f"https://api.github.com/repos/{source.full_name}/git/trees/{entry['sha']}?recursive=1")
    )
    if tree.get("truncated"):
        raise BoardCatalogError(f"GitHub truncated the {top}/ tree of {source.name}.")
    return [
        {**item, "path": f"{top}/{item['path']}"}
        for item in tree.get("tree", [])
        if item.get("type") == "blob" and str(item.get("path", "")).endswith(".ini")
    ]


def _read_ini(config: Config, source: FirmwareSource, sha: str, item: dict[str, Any]) -> tuple[str, str]:
    path = str(item["path"])
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


def _read_all(config: Config, source: FirmwareSource, sha: str, items: list[dict[str, Any]]) -> list[tuple[str, str]]:
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        return list(pool.map(lambda item: _read_ini(config, source, sha, item), items))


def _project_files(
    config: Config,
    source: FirmwareSource,
    sha: str,
    root: list[dict[str, Any]],
    variants_inis: list[dict[str, Any]],
) -> list[tuple[str, str]] | None:
    """platformio.ini plus its `extra_configs`, in the order PlatformIO loads them.

    `variants_inis` is every .ini under variants/, already listed for the board
    list; another directory a pattern names (`arch/` on older versions,
    `src/` for InkHUD's PlatformioConfig.ini) costs one more tree call. An
    entry the commit does not have is skipped, as PlatformIO skips it.
    None when the commit has no platformio.ini at all: a commit never changes,
    so that answer is final and is stored like any other.
    """
    root_entry = next((item for item in root if item.get("path") == "platformio.ini"), None)
    if root_entry is None:
        return None
    _path, root_ini = _read_ini(config, source, sha, root_entry)
    patterns = extra_config_patterns(root_ini)
    known: dict[str, dict[str, Any]] = {item["path"]: item for item in variants_inis}
    glob_tops = {pattern.split("/", 1)[0] for pattern in patterns if "/" in pattern and is_glob(pattern)}
    for top in sorted(glob_tops - {"variants"}):
        for item in _subtree_ini_files(source, root, top):
            known.setdefault(item["path"], item)
    for item in root:
        if item.get("type") == "blob" and str(item.get("path", "")).endswith(".ini"):
            known.setdefault(item["path"], item)
    # A literal entry under a directory not listed above: read it by path.
    for pattern in patterns:
        if not is_glob(pattern) and pattern not in known:
            known[pattern] = {"path": pattern, "literal": True}
    if len(known) > MAX_INI_FILES:
        raise BoardCatalogError(f"{source.name} has {len(known)} ini files, over the limit.")
    ordered = extra_config_paths(patterns, known)

    def read(item: dict[str, Any]) -> tuple[str, str] | None:
        try:
            return _read_ini(config, source, sha, item)
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and item.get("literal"):
                return None  # PlatformIO skips a listed file that does not exist
            raise

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        extras = [pair for pair in pool.map(read, [known[path] for path in ordered]) if pair is not None]
    return [("platformio.ini", root_ini), *extras]


def fetch_board_catalog(
    config: Config, source: FirmwareSource, sha: str
) -> tuple[list[Device], dict[str, str | None], bool]:
    """(devices, {env: PlatformIO Core}, complete) for one commit of one firmware.

    `complete` is False when the PlatformIO versions could not be worked out
    for a reason that may pass (network, rate limit): that answer is served
    but not stored, so a later request reads them again.
    """
    if not _SHA_RE.match(sha):
        raise BoardCatalogError(f"Not a commit SHA: {sha!r}")
    root = _root_tree(source, sha)
    if not any(item.get("path") == "variants" for item in root):
        raise BoardCatalogError(f"{source.name} has no variants/ directory at {sha[:7]}.")
    variants_inis = _subtree_ini_files(source, root, "variants")
    variant_inis = [item for item in variants_inis if item["path"].endswith("platformio.ini")]
    if len(variant_inis) > MAX_INI_FILES:
        raise BoardCatalogError(f"{source.name} has {len(variant_inis)} platformio.ini files, over the limit.")
    boards = parse_boards(_read_all(config, source, sha, variant_inis))
    if not boards:
        raise BoardCatalogError(f"No flashable boards found in {source.name} at {sha[:7]}.")
    devices = sync_devices(enabled_devices(config.root_dir), boards, strict=False).devices
    envs = sorted({env for device in devices for env in (device.platformio_env, device.mui_env, device.hybrid_env) if env})
    try:
        files = _project_files(config, source, sha, root, variants_inis)
        if files is None:
            return devices, {env: None for env in envs}, True
        return devices, platformio_for_envs(load_project(files), envs, _http_get), True
    except (PlatformLookupError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
        print(f"PlatformIO versions for {source.id}@{sha[:7]} unavailable for now: {exc}")
        return devices, {env: None for env in envs}, False


def fetch_board_devices(config: Config, source: FirmwareSource, sha: str) -> list[Device]:
    """The page's device list for one commit of one firmware."""
    return fetch_board_catalog(config, source, sha)[0]


def _load_cached(config: Config, firmware_id: str, sha: str) -> tuple[list[Device], dict[str, str | None]] | None:
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
    platformio = stored.get("platformio")
    return [Device(**item) for item in stored["devices"]], dict(platformio) if isinstance(platformio, dict) else {}


def _store(
    config: Config, firmware_id: str, sha: str, devices: list[Device], platformio: dict[str, str | None]
) -> None:
    payload = json.dumps(
        {"format": CATALOG_FORMAT, "devices": [asdict(device) for device in devices], "platformio": platformio}
    )
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
    devices, _platformio, from_firmware = catalog_for(config, source, sha)
    return [d for d in devices if exclusion_reason(d.platformio_env, d.family) is None], from_firmware


def catalog_for(config: Config, source: FirmwareSource, sha: str) -> tuple[list[Device], dict[str, str | None], bool]:
    """(devices, {env: PlatformIO Core}, from_firmware), without exclusions applied."""
    initialize_database(config)
    cached = _load_cached(config, source.id, sha)
    if cached is not None:
        return cached[0], cached[1], True
    with _lock_for((source.id, sha)):
        cached = _load_cached(config, source.id, sha)
        if cached is not None:
            return cached[0], cached[1], True
        try:
            devices, platformio, complete = fetch_board_catalog(config, source, sha)
        except (urllib.error.URLError, TimeoutError, BoardCatalogError, json.JSONDecodeError, KeyError) as exc:
            print(f"Board list for {source.id}@{sha[:7]} unavailable, using data/devices.json: {exc}")
            return enabled_devices(config.root_dir), {}, False
        if complete:
            _store(config, source.id, sha, devices, platformio)
        return devices, platformio, True


def platformio_for_build(config: Config, source: FirmwareSource, sha: str, env: str) -> str | None:
    """The Core to build `env` with, or None to let the builder pick it at build time."""
    if not _SHA_RE.match(sha):
        return None
    try:
        version = catalog_for(config, source, sha)[1].get(env)
    except Exception as exc:  # never fail a build over this: the builder can still pick
        print(f"PlatformIO version lookup for {source.id}@{sha[:7]} {env} failed: {exc}")
        return None
    return version if version and version != UNSUPPORTED else None


def platformio_unavailable(env: str, platformio: dict[str, str | None]) -> dict[str, str] | None:
    """The `unavailable` payload of a board whose platform needs a Core the image lacks."""
    if platformio.get(env) != UNSUPPORTED:
        return None
    return {"reason": "platformio_unsupported", "issue": PLATFORMIO_UNSUPPORTED_ISSUE}


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
            if platformio_unavailable(device.platformio_env, catalog_for(config, source, sha)[1]):
                where = f"con {source.name} {version}" if version else f"con {source.name}"
                raise ValueError(
                    f"{device.label} no esta disponible {where} "
                    f"({UNAVAILABLE_REASONS['platformio_unsupported']})."
                )
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
