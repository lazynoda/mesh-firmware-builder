"""The firmware sources the builder offers, read from data/firmwares.json.

Each entry is a GitHub repository that builds like upstream Meshtastic
(PlatformIO, userPrefs.jsonc at the root). Two ways to pick a version:

- "tags": the user picks one of the repository's tags, cached in SQLite.
- "branch": there are no releases; every build compiles the current head of
  one branch, and the commit it resolved to is stored with the build.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .code_options import parse_version


DEFAULT_FIRMWARE_ID = "meshtastic"
VERSIONING_TAGS = "tags"
VERSIONING_BRANCH = "branch"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_REPO_URL_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
_ENV_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_REASON_RE = re.compile(r"^[a-z_]{1,40}$")
_FIXED_VERSION_RE = re.compile(r"^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}$")
_ISSUE_URL_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[0-9]+$")


@dataclass(frozen=True)
class UnavailableBoard:
    """A board the firmware offers that cannot be built with it right now.

    It stays in the device list, marked, so users see why instead of the board
    silently missing; submissions for it are refused. `reason` is a code the
    page translates (`device.unavailable.<reason>`), `issue` tracks the fix.
    """

    env: str
    reason: str
    issue: str
    # First firmware version (x.y.z) that builds this board. None = no fixed
    # release yet, so every version is refused.
    fixed_since: str | None = None

    def applies_to(self, version: str | None) -> bool:
        """Whether `version` still has the problem. A version that does not parse
        (or none at all) is treated as affected: refusing is the safe side."""
        if self.fixed_since is None:
            return True
        current = parse_version(version or "")
        return current is None or current < parse_version(self.fixed_since)

    def public(self) -> dict[str, str]:
        payload = {"reason": self.reason, "issue": self.issue}
        if self.fixed_since is not None:
            payload["fixedSinceFirmwareVersion"] = self.fixed_since
        return payload


@dataclass(frozen=True)
class FirmwareSource:
    id: str
    name: str
    url: str
    owner: str
    repo: str
    versioning: str
    branch: str | None = None
    license: str = "GPL-3.0-or-later"
    unavailable_boards: tuple[UnavailableBoard, ...] = ()

    def unavailable(self, env: str, version: str | None = None) -> UnavailableBoard | None:
        """The entry blocking `env` at `version` (x.y.z or tag), if any."""
        return next(
            (item for item in self.unavailable_boards if item.env == env and item.applies_to(version)),
            None,
        )

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.full_name}.git"

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "versioning": self.versioning,
            "branch": self.branch,
        }


def firmwares_path(root_dir: Path) -> Path:
    return root_dir / "data" / "firmwares.json"


def _parse_entry(raw: object) -> FirmwareSource:
    if not isinstance(raw, dict):
        raise ValueError("Each firmware entry must be an object.")
    firmware_id = str(raw.get("id", ""))
    if not _ID_RE.match(firmware_id):
        raise ValueError(f"Invalid firmware id: {firmware_id!r}")
    name = str(raw.get("name", "")).strip()
    if not name:
        raise ValueError(f"Firmware {firmware_id} has no name.")
    url = str(raw.get("url", "")).strip()
    match = _REPO_URL_RE.match(url)
    if match is None:
        raise ValueError(f"Firmware {firmware_id}: url must be https://github.com/<owner>/<repo>.")
    versioning = str(raw.get("versioning", VERSIONING_TAGS))
    if versioning not in {VERSIONING_TAGS, VERSIONING_BRANCH}:
        raise ValueError(f"Firmware {firmware_id}: versioning must be 'tags' or 'branch'.")
    branch = raw.get("branch")
    if versioning == VERSIONING_BRANCH:
        if not isinstance(branch, str) or not _BRANCH_RE.match(branch) or ".." in branch:
            raise ValueError(f"Firmware {firmware_id}: branch versioning needs a valid 'branch'.")
    else:
        branch = None
    unavailable = _parse_unavailable(firmware_id, raw.get("unavailableBoards"))
    return FirmwareSource(
        id=firmware_id,
        name=name,
        url=url.rstrip("/"),
        owner=match.group(1),
        repo=match.group(2),
        versioning=versioning,
        branch=branch,
        license=str(raw.get("license") or "GPL-3.0-or-later"),
        unavailable_boards=unavailable,
    )


def _parse_unavailable(firmware_id: str, raw: object) -> tuple[UnavailableBoard, ...]:
    """`{"<platformio env>": {"reason": "<code>", "issue": "<GitHub issue URL>",
    "fixedSinceFirmwareVersion": "<x.y.z, optional>"}}`."""
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        raise ValueError(f"Firmware {firmware_id}: unavailableBoards must be an object keyed by env.")
    boards = []
    for env, spec in raw.items():
        if not isinstance(env, str) or not _ENV_RE.match(env):
            raise ValueError(f"Firmware {firmware_id}: invalid env in unavailableBoards: {env!r}")
        if not isinstance(spec, dict):
            raise ValueError(f"Firmware {firmware_id}: unavailableBoards.{env} must be an object.")
        reason = str(spec.get("reason", ""))
        issue = str(spec.get("issue", ""))
        if not _REASON_RE.match(reason):
            raise ValueError(f"Firmware {firmware_id}: unavailableBoards.{env} needs a reason code.")
        if not _ISSUE_URL_RE.match(issue):
            raise ValueError(f"Firmware {firmware_id}: unavailableBoards.{env} needs a GitHub issue URL.")
        fixed_since = spec.get("fixedSinceFirmwareVersion")
        if fixed_since is not None:
            if not isinstance(fixed_since, str) or not _FIXED_VERSION_RE.match(fixed_since):
                raise ValueError(
                    f"Firmware {firmware_id}: unavailableBoards.{env}.fixedSinceFirmwareVersion must be x.y.z."
                )
        boards.append(UnavailableBoard(env=env, reason=reason, issue=issue, fixed_since=fixed_since))
    return tuple(boards)


# Used when data/firmwares.json is absent, so an install that predates the file
# keeps building upstream exactly as before.
UPSTREAM_ENTRY = {
    "id": DEFAULT_FIRMWARE_ID,
    "name": "Meshtastic® Oficial",
    "url": "https://github.com/meshtastic/firmware",
    "versioning": VERSIONING_TAGS,
}


def load_firmware_catalog(root_dir: Path) -> tuple[str, list[FirmwareSource]]:
    path = firmwares_path(root_dir)
    if not path.exists():
        return DEFAULT_FIRMWARE_ID, [_parse_entry(UPSTREAM_ENTRY)]
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = [_parse_entry(item) for item in payload.get("firmwares", [])]
    if not entries:
        raise ValueError("data/firmwares.json lists no firmwares.")
    ids = [item.id for item in entries]
    if len(set(ids)) != len(ids):
        raise ValueError("data/firmwares.json repeats a firmware id.")
    default = str(payload.get("default") or entries[0].id)
    if default not in ids:
        raise ValueError(f"Default firmware {default!r} is not in the list.")
    return default, entries


def list_firmwares(root_dir: Path) -> list[FirmwareSource]:
    return load_firmware_catalog(root_dir)[1]


def get_firmware(root_dir: Path, firmware_id: str | None) -> FirmwareSource:
    default, entries = load_firmware_catalog(root_dir)
    wanted = firmware_id or default
    for item in entries:
        if item.id == wanted:
            return item
    raise ValueError(f"Firmware desconocido: {wanted}")
