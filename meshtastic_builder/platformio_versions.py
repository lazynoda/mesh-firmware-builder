"""Which PlatformIO Core each board of each firmware version builds with.

A board's env names a development platform (`platform = ...` after resolving
`extends`), and that platform declares the Core it needs in its own
platform.json (`engines.platformio`). Platforms only state a minimum, never a
maximum, and a newer Core can still break an older platform halfway through a
build: PlatformIO 6.2.0 swaps in SCons 4.11, which dropped the module the
pioarduino 55.03.311 ESP32 link step imports. So each board gets the LOWEST
Core in the image that satisfies its platform, never the newest.

The answer is read once per commit, together with the board list (it is stored
in the same board_catalogs row), from GitHub: the repository tree, the
platformio.ini files PlatformIO itself would load (the root file plus its
`extra_configs` globs), and the platform.json of each distinct platform. A
board whose platform could not be read gets no version; the builder then picks
one at build time (see docker/build_firmware.sh). A board whose platform needs
a Core this image does not have is listed as unavailable instead of failing.
"""

from __future__ import annotations

import configparser
import fnmatch
import json
import re
import threading
import urllib.error
from collections.abc import Callable, Iterable

# Every PlatformIO Core the builder image carries, lowest first. The first one
# is the image's default `pio`. Keep in step with docker/builder.Dockerfile.
PLATFORMIO_VERSIONS: tuple[str, ...] = ("6.1.19", "6.2.0")

# Marker stored instead of a version when no Core in the image fits.
UNSUPPORTED = "unsupported"

MAX_EXTENDS_STEPS = 64
MAX_PLATFORM_JSON_BYTES = 256 * 1024

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_GITHUB = r"https://github\.com/(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)"
# How firmwares name platforms. Anything else is left unresolved on purpose.
_REGISTRY_RE = re.compile(r"^(?:platformio/)?(?P<name>[a-z0-9_-]+)@\s*=?\s*(?P<version>\d+\.\d+\.\d+)$")
_ARCHIVE_RE = re.compile(_GITHUB + r"/archive/(?:refs/(?:heads|tags)/)?(?P<ref>[A-Za-z0-9_.+-]+)\.(?:zip|tar\.gz)$")
_RELEASE_RE = re.compile(_GITHUB + r"/releases/download/(?P<ref>[A-Za-z0-9_.+-]+)/[A-Za-z0-9_.+-]+$")
_GIT_RE = re.compile(_GITHUB + r"(?:\.git)?/?(?:#(?P<ref>[A-Za-z0-9_./+-]+))?$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

_engine_cache: dict[str, str | None] = {}
_engine_lock = threading.Lock()


class PlatformLookupError(RuntimeError):
    """A platform or project file could not be read for a reason that may pass
    (network, rate limit). The caller must not store the result."""


def platform_json_source(spec: str) -> tuple[str, str, bool] | None:
    """(repo, ref, immutable) of the GitHub copy of a platform's platform.json.

    Registry platforms (`platformio/espressif32@6.13.0`) are published from
    the matching `v<version>` tag of platformio/platform-<name>. A version
    range (`^10.8.0`) is not resolved: which version PlatformIO picks depends
    on the registry on the day of the build.
    """
    spec = spec.strip()
    match = _REGISTRY_RE.match(spec)
    if match:
        return f"platformio/platform-{match['name']}", f"v{match['version']}", True
    for pattern in (_ARCHIVE_RE, _RELEASE_RE):
        match = pattern.match(spec)
        if match:
            ref = match["ref"]
            return match["repo"], ref, True
    match = _GIT_RE.match(spec)
    if match:
        ref = match["ref"] or "HEAD"
        return match["repo"], ref, bool(_SHA_RE.match(ref))
    return None


def _parse_version(text: str) -> tuple[int, ...] | None:
    parts = text.strip().split(".")
    if not 1 <= len(parts) <= 3 or not all(part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    return tuple(numbers + [0] * (3 - len(numbers)))


def _clause_ok(clause: str, version: tuple[int, ...]) -> bool | None:
    """One clause of a semantic_version SimpleSpec, as PlatformIO evaluates it."""
    clause = clause.strip()
    if clause in ("", "*"):
        return True
    match = re.match(r"^(\^|~=|~|>=|<=|==|!=|>|<|=)?\s*(.+)$", clause)
    if match is None:
        return None
    operator, raw = match.group(1) or "==", match.group(2)
    if raw.endswith((".*", ".x")):
        raw = raw[:-2]
        operator = operator if operator != "==" else "~"
    parts = raw.split(".")
    target = _parse_version(raw)
    if target is None:
        return None
    if operator == "^":
        # ^1.2.3 := >=1.2.3,<2.0.0 ; ^0.2.3 := >=0.2.3,<0.3.0 (major 0 pins the minor)
        upper = (target[0] + 1, 0, 0) if target[0] else (0, target[1] + 1, 0)
        return target <= version < upper
    if operator in ("~", "~="):
        upper = (target[0] + 1, 0, 0) if len(parts) == 1 else (target[0], target[1] + 1, 0)
        return target <= version < upper
    return {
        ">=": version >= target,
        "<=": version <= target,
        ">": version > target,
        "<": version < target,
        "==": version == target,
        "=": version == target,
        "!=": version != target,
    }[operator]


def spec_allows(spec: str, version: str) -> bool | None:
    """Whether a Core version satisfies an `engines.platformio` value (None: unreadable)."""
    target = _parse_version(version)
    if target is None:
        return None
    results = [_clause_ok(clause, target) for clause in spec.split(",")]
    if any(result is None for result in results):
        return None
    return all(results)


def pick_platformio(engine: str | None) -> str | None:
    """The lowest Core in the image a platform accepts, UNSUPPORTED, or None when unknown.

    No `engines.platformio` means any Core. Like PlatformIO itself, a platform
    written for Core 2-5 counts as compatible with every 6.x (see
    platformio/platform/base.py ensure_engine_compatible).
    """
    if engine is None:
        return None
    if engine == "":
        return PLATFORMIO_VERSIONS[0]
    legacy = [spec_allows(engine, f"{major}.0.0") for major in (2, 3, 4, 5)]
    if any(legacy):
        return PLATFORMIO_VERSIONS[0]
    for version in PLATFORMIO_VERSIONS:
        allowed = spec_allows(engine, version)
        if allowed is None:
            return None
        if allowed:
            return version
    return UNSUPPORTED


def platform_engine(spec: str, http_get: Callable[[str], str]) -> str | None:
    """`engines.platformio` of a platform ("" when it sets none), or None when unknowable.

    None is final (a spec we do not resolve, a missing or broken platform.json).
    A failure that may pass raises PlatformLookupError instead.
    """
    with _engine_lock:
        if spec in _engine_cache:
            return _engine_cache[spec]
    where = platform_json_source(spec)
    if where is None:
        return None
    repo, ref, immutable = where
    try:
        body = http_get(f"https://raw.githubusercontent.com/{repo}/{ref}/platform.json")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            print(f"platform.json of {spec} not found")
            return None
        raise PlatformLookupError(f"platform.json of {spec}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PlatformLookupError(f"platform.json of {spec}: {exc}") from exc
    try:
        if len(body) > MAX_PLATFORM_JSON_BYTES:
            return None
        manifest = json.loads(body)
        engines = manifest.get("engines") or {}
        engine = str(engines.get("platformio", "")).strip() if isinstance(engines, dict) else ""
    except (json.JSONDecodeError, AttributeError, ValueError) as exc:
        print(f"platform.json of {spec} unreadable: {exc}")
        return None
    if immutable:
        with _engine_lock:
            _engine_cache[spec] = engine
    return engine


def extra_config_patterns(root_ini: str) -> list[str]:
    """The `extra_configs` entries of a platformio.ini, as written."""
    parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"), interpolation=None, strict=False)
    try:
        parser.read_string(root_ini, source="platformio.ini")
    except configparser.Error:
        return []
    if not parser.has_option("platformio", "extra_configs"):
        return []
    raw = parser.get("platformio", "extra_configs")
    return [item.strip().strip("/") for item in raw.split("\n" if "\n" in raw else ",") if item.strip()]


def is_glob(pattern: str) -> bool:
    return any(ch in pattern for ch in "*?[")


def extra_config_paths(patterns: Iterable[str], paths: Iterable[str]) -> list[str]:
    """The files PlatformIO loads after platformio.ini, in order, among `paths`.

    Same matching as Python's glob (which PlatformIO uses): `*` never crosses
    a `/` and does not match names starting with a dot; each pattern's matches
    in sorted order, a file matched twice loaded once.
    """
    available = sorted(set(paths))
    ordered: list[str] = []
    for pattern in patterns:
        pattern_parts = pattern.strip("/").split("/")
        for path in available:
            parts = path.split("/")
            if len(parts) != len(pattern_parts) or path in ordered:
                continue
            if all(
                fnmatch.fnmatchcase(part, wanted) and not (part.startswith(".") and not wanted.startswith("."))
                for part, wanted in zip(parts, pattern_parts)
            ):
                ordered.append(path)
    return ordered


def load_project(files: Iterable[tuple[str, str]]) -> configparser.ConfigParser:
    """One parser over the given (path, text) pairs, in the given order, as PlatformIO merges them."""
    parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"), interpolation=None, strict=False)
    for path, text in files:
        probe = configparser.ConfigParser(inline_comment_prefixes=("#", ";"), interpolation=None, strict=False)
        try:
            probe.read_string(text, source=path)
        except configparser.Error:
            continue
        parser.read_string(text, source=path)
    return parser


def env_platform(parser: configparser.ConfigParser, env: str) -> str | None:
    """The `platform` an env builds with, resolving `extends` like PlatformIO.

    Same walk as device_sync._resolve: the env's own section, then its
    `extends` chain (last listed first), then the global [env]. Values with
    `${...}` interpolation are not resolved (no firmware uses it for this key).
    """
    queue = ["env", f"env:{env}"]
    seen: set[str] = set()
    steps = 0
    while queue and steps < MAX_EXTENDS_STEPS:
        section = queue.pop()
        steps += 1
        if section in seen or not parser.has_section(section):
            continue
        seen.add(section)
        if parser.has_option(section, "platform"):
            lines = [line.strip() for line in parser.get(section, "platform").splitlines()]
            values = [line for line in lines if line and not line.startswith(("#", ";"))]
            if len(values) != 1 or "${" in values[0]:
                return None
            return values[0]
        if parser.has_option(section, "extends"):
            raw = parser.get(section, "extends")
            queue.extend(item.strip() for item in raw.split("\n" if "\n" in raw else ",") if item.strip())
    return None


def platformio_for_envs(
    parser: configparser.ConfigParser, envs: Iterable[str], http_get: Callable[[str], str]
) -> dict[str, str | None]:
    """{env: Core version, UNSUPPORTED or None (unknown)} for the given envs."""
    result: dict[str, str | None] = {}
    for env in envs:
        spec = env_platform(parser, env)
        result[env] = pick_platformio(platform_engine(spec, http_get)) if spec else None
    return result
