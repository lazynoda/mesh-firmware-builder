from __future__ import annotations

import json
from typing import Any

from .code_options import load_build_options, long_name_max_bytes, max_channels, validate_code_options
from .config import Config
from .db import create_build_request, public_build_view
from .board_catalog import get_device_for_build
from .firmware import get_userprefs_template, resolve_supported_version
from .firmwares import VERSIONING_BRANCH, get_firmware
from .jsonc import validate_and_merge_userprefs


OWNER_NAME_KEYS = ("USERPREFS_CONFIG_OWNER_LONG_NAME", "USERPREFS_CONFIG_OWNER_SHORT_NAME")


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Falta el campo {key}.")
    return value


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"El campo {key} debe ser texto.")
    return value.strip() or None


def create_build_submission(config: Config, payload: dict[str, Any]) -> dict[str, Any]:
    device_id = _required_str(payload, "deviceId")
    # Absent on clients older than the firmware selector: those meant upstream.
    source = get_firmware(config.root_dir, _optional_str(payload, "firmwareId"))
    firmware_tag = _optional_str(payload, "firmwareTag")
    if source.versioning != VERSIONING_BRANCH and not firmware_tag:
        raise ValueError("Falta el campo firmwareTag.")
    version = resolve_supported_version(config, firmware_tag, firmware_id=source.id)
    # Checked against the boards of this exact commit, so a board the chosen
    # firmware or tag lacks is refused here instead of failing to compile.
    mui = payload.get("mui", False)
    if not isinstance(mui, bool):
        raise ValueError("El campo mui debe ser true o false.")
    hybrid = payload.get("hybrid", False)
    if not isinstance(hybrid, bool):
        raise ValueError("El campo hybrid debe ser true o false.")
    device = get_device_for_build(
        config, source, version["sha"], device_id, mui=mui, hybrid=hybrid, version=version["version"]
    )
    # Version gates (patches, channel count, code options) compare x.y.z, which
    # for a branch comes from its version.properties rather than from a tag.
    gate_version = version["version"]
    prefs_raw = _required_str(payload, "prefsJsonc")
    code_options, code_macros = validate_code_options(
        config.root_dir,
        payload.get("codeOptions"),
        gate_version,
    )
    template_ref = version["sha"] if version["branch"] else version["tag"]
    template = get_userprefs_template(config, version["tag"], firmware_id=source.id, ref=template_ref)
    prefs_jsonc, prefs = validate_and_merge_userprefs(
        prefs_raw,
        template,
        config.max_prefs_bytes,
        extra_keys=code_macros,
        max_channels=max_channels(load_build_options(config.root_dir), gate_version),
    )
    # Every node needs a name of its own. The form used to prefill one and a
    # lot of nodes went out as "Mi nodo Meshtastic"; API clients must send them too.
    for key in OWNER_NAME_KEYS:
        if not str(prefs.get(key) or "").strip():
            raise ValueError("Falta el nombre largo o el nombre corto del nodo.")
    # The firmware cuts a longer name on first boot, and a character cut in half
    # becomes "?" (a 29-byte name ending in emoji came out as "...🏡???").
    max_long = long_name_max_bytes(load_build_options(config.root_dir), gate_version)
    long_bytes = len(str(prefs["USERPREFS_CONFIG_OWNER_LONG_NAME"]).encode("utf-8"))
    if long_bytes > max_long:
        raise ValueError(
            f"El nombre largo ocupa {long_bytes} bytes y esta version de firmware solo guarda {max_long}."
        )
    row = create_build_request(
        config,
        device_id=device.id,
        platformio_env=device.platformio_env,
        firmware_tag=version["tag"],
        firmware_sha=version["sha"],
        prefs_jsonc=prefs_jsonc,
        code_options=json.dumps(code_options, sort_keys=True) if code_options else None,
        firmware_id=source.id,
        firmware_version=gate_version,
        device_label=device.label,
    )
    token = row["public_token"]
    return {
        "row": row,
        "public": public_build_view(row),
        "buildUrl": f"{config.base_url}/build/{token}",
        "statusUrl": f"{config.base_url}/api/builds/{token}",
        "downloadUrl": f"{config.base_url}/download/{token}",
    }
