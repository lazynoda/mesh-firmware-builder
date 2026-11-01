from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Device:
    id: str
    label: str
    platformio_env: str
    family: str
    enabled: bool
    # The `<env>-tft` build of this board (Meshtastic UI), when the firmware has one.
    mui_env: str | None = None
    # The `<env>-hybrid` build (Jentastic: JenCore + RNode compiled in), when it has one.
    hybrid_env: str | None = None


def load_devices(root_dir: Path) -> list[Device]:
    path = root_dir / "data" / "devices.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Device(**item) for item in raw]


def enabled_devices(root_dir: Path) -> list[Device]:
    return [device for device in load_devices(root_dir) if device.enabled]


def get_enabled_device(root_dir: Path, device_id: str) -> Device:
    for device in enabled_devices(root_dir):
        if device.id == device_id:
            return device
    raise ValueError("Dispositivo no soportado.")

