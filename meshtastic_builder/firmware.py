from __future__ import annotations

import json
import re
from datetime import timedelta
from email.message import Message
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import __version__
from .code_options import parse_version
from .config import Config
from .db import (
    get_firmware_version,
    list_firmware_versions,
    parse_iso,
    retire_missing_tags,
    upsert_firmware_versions,
    utc_now,
)
from .firmwares import DEFAULT_FIRMWARE_ID, VERSIONING_BRANCH, FirmwareSource, get_firmware
from .security import safe_tag_for_path


# How long a resolved branch head is trusted before GitHub is asked again. Page
# loads and submissions both resolve it, and unauthenticated API calls are
# limited to 60 an hour per IP.
BRANCH_HEAD_TTL = timedelta(minutes=5)

_VERSION_PROPERTIES_RE = {
    key: re.compile(rf"^\s*{key}\s*=\s*(\d+)\s*$", re.MULTILINE) for key in ("major", "minor", "build")
}


class FirmwareLookupError(RuntimeError):
    pass


def _http_get(url: str, timeout: int = 15) -> tuple[str, Message]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": f"meshtastic-builder/{__version__}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8"), response.headers


def _http_get_text(url: str, timeout: int = 15) -> str:
    body, _headers = _http_get(url, timeout=timeout)
    return body


def _next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.strip()
        if 'rel="next"' not in section:
            continue
        if section.startswith("<") and ">" in section:
            return section[1 : section.index(">")]
    return None


def _source(config: Config, source: FirmwareSource | str | None) -> FirmwareSource:
    if isinstance(source, FirmwareSource):
        return source
    return get_firmware(config.root_dir, source)


def tags_url(config: Config, source: FirmwareSource) -> str:
    # MB_GITHUB_TAGS_URL predates the firmware list and still overrides upstream's.
    if source.id == DEFAULT_FIRMWARE_ID:
        return config.github_tags_url
    return f"https://api.github.com/repos/{source.full_name}/tags?per_page=100"


def releases_url(source: FirmwareSource) -> str:
    return f"https://api.github.com/repos/{source.full_name}/releases?per_page=100"


# What a tag must look like to be offered: `vX.Y.Z`, then nothing, `.<commit>`
# (upstream's `v2.8.2.d5f1619`) or a SemVer pre-release `-<id>` (`v2.8.201-rc.3`).
# The version gates read the leading x.y.z, so anything else would be compared
# as "old firmware" (advanced options refused, 3 channels, 39-byte long name).
TAG_RE = re.compile(r"^v\d+\.\d+\.\d+(?:\.[0-9a-f]{7,40}|-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?$")

# Upstream does not delete a withdrawn release: it appends "(Revoked)" to its
# title and publishes a new one. The title is the only place that says so.
_REVOKED_RE = re.compile(r"\brevoked\b", re.IGNORECASE)


def valid_tag(tag: str) -> bool:
    return len(tag) <= 80 and TAG_RE.match(tag) is not None


def version_sort_key(item: dict[str, Any]) -> tuple[tuple[int, int, int], str, str]:
    """Newest first when sorted in reverse.

    The x.y.z decides, compared as numbers (2.8.105 > 2.8.99). Tags of the same
    x.y.z (a re-release `v2.8.2.4c89b69` / `v2.8.2.d5f1619`, `-rc.9` / `-rc.10`)
    are ordered by release date, not by the tag text. The date never decides
    across versions: a 2.7 hotfix published after 2.8.0 is still older.
    """
    tag = str(item.get("tag") or "")
    return (parse_version(tag) or (0, 0, 0), str(item.get("published_at") or ""), tag)


def _paged(url: str | None, max_pages: int) -> tuple[list[dict[str, Any]], bool]:
    """Every item of a paginated GitHub list, and whether the last page was reached."""
    items: list[dict[str, Any]] = []
    pages = 0
    while url and pages < max_pages:
        raw, headers = _http_get(url)
        payload = json.loads(raw)
        if not isinstance(payload, list):
            raise FirmwareLookupError("La respuesta de GitHub no es una lista.")
        items.extend(item for item in payload if isinstance(item, dict))
        pages += 1
        url = _next_link(headers.get("Link"))
    return items, url is None


def _published_releases(config: Config, source: FirmwareSource) -> tuple[dict[str, dict[str, Any]], bool]:
    """tag -> {name, published_at, revoked} for the repository's published releases."""
    items, complete = _paged(releases_url(source), config.github_max_tag_pages)
    releases: dict[str, dict[str, Any]] = {}
    for item in items:
        tag = item.get("tag_name")
        if not isinstance(tag, str) or not tag or item.get("draft"):
            continue
        name = item.get("name") if isinstance(item.get("name"), str) else ""
        releases[tag] = {
            "name": name or tag,
            "published_at": item.get("published_at"),
            "revoked": bool(_REVOKED_RE.search(name)),
        }
    return releases, complete


def raw_url(config: Config, source: FirmwareSource, ref: str, path: str) -> str:
    if source.id == DEFAULT_FIRMWARE_ID and path == "userPrefs.jsonc":
        return config.raw_userprefs_url.format(tag=ref)
    return f"https://raw.githubusercontent.com/{source.full_name}/{ref}/{path}"


def parse_version_properties(text: str) -> str | None:
    """`major = 2 / minor = 8 / build = 1` -> `2.8.1`, the firmware's own version."""
    parts = []
    for key in ("major", "minor", "build"):
        match = _VERSION_PROPERTIES_RE[key].search(text)
        if match is None:
            return None
        parts.append(match.group(1))
    return ".".join(parts)


def refresh_firmware_versions(
    config: Config,
    source: FirmwareSource | str | None = None,
) -> list[dict[str, Any]]:
    source = _source(config, source)
    if source.versioning == VERSIONING_BRANCH:
        return [resolve_branch_head(config, source)]

    # A version is offered only when it is a published release (the author
    # says "this is for users") and its tag has a format the gates can read.
    # The commit comes from the tag: a release object does not carry it.
    releases, releases_complete = _published_releases(config, source)
    tags, tags_complete = _paged(tags_url(config, source), config.github_max_tag_pages)

    versions: list[dict[str, Any]] = []
    seen_tags: set[str] = set()
    for item in tags:
        tag = item.get("name")
        sha = (item.get("commit") or {}).get("sha")
        if not isinstance(tag, str) or not tag or not sha or tag in seen_tags:
            continue
        seen_tags.add(tag)
        release = releases.get(tag)
        if release is None or not valid_tag(tag):
            continue
        supported = (
            1
            if config.auto_support_latest_tags <= 0
            or len(versions) < config.auto_support_latest_tags
            else 0
        )
        versions.append(
            {
                "tag": tag,
                "sha": sha,
                "release_name": release["name"],
                "published_at": release["published_at"],
                "supported": supported,
                "revoked": 1 if release["revoked"] else 0,
                "smoke_test_status": "untested",
            }
        )

    if not versions:
        raise FirmwareLookupError("GitHub no devolvio releases utilizables.")

    upsert_firmware_versions(config, versions, firmware_id=source.id)
    if tags_complete and releases_complete:
        # A tag that is gone, lost its release or does not have a valid format
        # stops being offered (its commit may no longer be fetchable). Only
        # after reading every page of both lists, or a page cap would retire
        # the oldest ones. Rows stay, unsupported, so old builds still resolve;
        # a version that comes back needs `set-supported` by hand.
        retire_missing_tags(config, source.id, {item["tag"] for item in versions})
    return versions


def resolve_branch_head(config: Config, source: FirmwareSource) -> dict[str, Any]:
    """Ask GitHub for the branch's current commit and that commit's version.properties.

    Stored in firmware_versions under the branch name, with the firmware's own
    version (e.g. 2.8.1) as release_name, so the version gates have something
    to compare and a GitHub outage still leaves the last known head usable.
    """
    branch = str(source.branch)
    raw, _headers = _http_get(f"https://api.github.com/repos/{source.full_name}/commits/{branch}")
    payload = json.loads(raw)
    sha = payload.get("sha") if isinstance(payload, dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise FirmwareLookupError(f"GitHub no devolvio el commit de la rama {branch}.")
    version = parse_version_properties(_http_get_text(raw_url(config, source, sha, "version.properties")))
    if version is None:
        raise FirmwareLookupError(f"No se pudo leer version.properties de {source.name}.")
    item = {
        "tag": branch,
        "sha": sha,
        "release_name": version,
        "published_at": None,
        "supported": 1,
        "smoke_test_status": "untested",
    }
    upsert_firmware_versions(config, [item], firmware_id=source.id)
    return get_firmware_version(config, branch, firmware_id=source.id) or item


def _branch_head(config: Config, source: FirmwareSource, *, force_refresh: bool) -> dict[str, Any]:
    cached = get_firmware_version(config, str(source.branch), firmware_id=source.id)
    fresh = cached is not None and utc_now() - parse_iso(cached["last_checked_at"]) < BRANCH_HEAD_TTL
    if cached is not None and fresh and not force_refresh:
        return cached
    try:
        return resolve_branch_head(config, source)
    except (urllib.error.URLError, TimeoutError, FirmwareLookupError, json.JSONDecodeError):
        if cached is None:
            raise FirmwareLookupError(f"No se pudo resolver la rama de {source.name} y no hay cache local.")
        return cached


def firmware_version_of(source: FirmwareSource, version: dict[str, Any]) -> str:
    """The x.y.z the version gates compare: the tag, or version.properties for a branch."""
    if source.versioning == VERSIONING_BRANCH:
        return str(version.get("release_name") or "")
    return str(version["tag"])


def public_version(source: FirmwareSource, version: dict[str, Any]) -> dict[str, Any]:
    return {
        **version,
        "firmwareId": source.id,
        "version": firmware_version_of(source, version),
        "branch": source.versioning == VERSIONING_BRANCH,
        "revoked": bool(version.get("revoked")),
    }


def list_versions_with_refresh(
    config: Config,
    *,
    force_refresh: bool = False,
    firmware_id: str | None = None,
) -> list[dict[str, Any]]:
    source = _source(config, firmware_id)
    if source.versioning == VERSIONING_BRANCH:
        return [public_version(source, _branch_head(config, source, force_refresh=force_refresh))]

    if force_refresh or not list_firmware_versions(config, supported_only=False, firmware_id=source.id):
        try:
            refresh_firmware_versions(config, source)
        except (urllib.error.URLError, TimeoutError, FirmwareLookupError, json.JSONDecodeError):
            if not list_firmware_versions(config, supported_only=False, firmware_id=source.id):
                raise FirmwareLookupError(
                    f"No se pudieron obtener tags de {source.name} y no hay cache local."
                )
    versions = list_firmware_versions(config, supported_only=True, firmware_id=source.id)
    # Newest first: rows are stored in insertion order, so tags added by a later refresh would sink to the bottom.
    versions.sort(key=version_sort_key, reverse=True)
    return [public_version(source, item) for item in versions]


def resolve_supported_version(
    config: Config,
    tag: str | None,
    firmware_id: str | None = None,
) -> dict[str, Any]:
    source = _source(config, firmware_id)
    if source.versioning == VERSIONING_BRANCH:
        # There is nothing to choose: always the branch head, whatever was sent.
        return public_version(source, _branch_head(config, source, force_refresh=False))

    if not tag:
        raise ValueError("Falta el tag de firmware.")
    version = get_firmware_version(config, tag, firmware_id=source.id)
    if version is None:
        try:
            refresh_firmware_versions(config, source)
        except Exception as exc:  # noqa: BLE001 - surface as domain error
            raise FirmwareLookupError(f"No se pudo refrescar la lista de tags: {exc}") from exc
        version = get_firmware_version(config, tag, firmware_id=source.id)

    if version is None:
        raise FirmwareLookupError("Version de firmware no encontrada.")
    if not version["supported"]:
        raise FirmwareLookupError("Version de firmware no soportada por el builder.")
    return public_version(source, version)


def userprefs_cache_path(config: Config, ref: str, firmware_id: str = DEFAULT_FIRMWARE_ID) -> Path:
    # Upstream keeps the path it had before other firmwares existed, so the cache survives the upgrade.
    base = config.cache_dir / "userprefs"
    if firmware_id != DEFAULT_FIRMWARE_ID:
        base = base / firmware_id
    return base / f"{safe_tag_for_path(ref)}.jsonc"


def get_userprefs_template(
    config: Config,
    tag: str,
    *,
    force_refresh: bool = False,
    firmware_id: str | None = None,
    ref: str | None = None,
) -> str:
    """The firmware's own userPrefs.jsonc at `ref` (defaults to the tag).

    A branch moves, so its callers pass the resolved commit as `ref`: the cache
    is then per commit and never serves a stale head.
    """
    source = _source(config, firmware_id)
    ref = ref or tag
    cache_path = userprefs_cache_path(config, ref, source.id)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists() and not force_refresh:
        return cache_path.read_text(encoding="utf-8")

    url = raw_url(config, source, ref, "userPrefs.jsonc")
    try:
        text = _http_get_text(url)
        if "USERPREFS_" not in text:
            raise FirmwareLookupError("El userPrefs.jsonc remoto no contiene claves USERPREFS.")
        cache_path.write_text(text, encoding="utf-8")
        return text
    except Exception:
        fallback = config.root_dir / "data" / "userPrefs.fallback.jsonc"
        return fallback.read_text(encoding="utf-8")
