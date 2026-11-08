from __future__ import annotations

import json
import mimetypes
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import __version__
from .code_options import load_build_options
from .config import Config, ensure_directories, load_config
from .cleanup import build_is_expired, expire_build_artifact
from .db import build_stats, get_build_by_token, initialize_database, public_build_view
from .devices import Device, enabled_devices
from .board_catalog import catalog_for, platformio_unavailable
from .device_sync import exclusion_reason
from .firmwares import DEFAULT_FIRMWARE_ID, FirmwareSource, get_firmware, load_firmware_catalog
from .firmware import (
    FirmwareLookupError,
    get_userprefs_template,
    list_versions_with_refresh,
    resolve_supported_version,
)
from .jsonc import JsoncValidationError
from .queue_eta import queue_view
from .security import validate_public_token
from .submissions import create_build_submission


RATE_LIMIT: dict[str, list[float]] = {}

VERSION_PLACEHOLDER = b"__MB_VERSION__"


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _public_error(message: str) -> dict[str, str]:
    return {"error": message}


def device_json(
    device: Device,
    source: FirmwareSource | None,
    version: str | None = None,
    platformio: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": device.id,
        "label": device.label,
        "platformioEnv": device.platformio_env,
        "family": device.family,
    }
    if device.mui_env:
        payload["mui"] = True
    if device.hybrid_env:
        payload["hybrid"] = True
    # Only for boards the selected firmware cannot build at this version: still
    # listed, with why and, when known, the first version that builds it.
    unavailable = source.unavailable(device.platformio_env, version) if source is not None else None
    if unavailable is not None:
        payload["unavailable"] = unavailable.public()
    # Its platform needs a PlatformIO Core the builder image does not carry yet.
    needs_core = platformio_unavailable(device.platformio_env, platformio or {})
    if needs_core is not None:
        payload["unavailable"] = needs_core
    return payload


class MeshtasticBuilderHandler(BaseHTTPRequestHandler):
    server_version = f"MeshtasticBuilder/{__version__}"
    config: Config

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:  # noqa: N802
        return self.handle_get_like(send_body=True)

    def do_HEAD(self) -> None:  # noqa: N802
        return self.handle_get_like(send_body=False)

    def handle_get_like(self, *, send_body: bool) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path == "/":
                # Builds used to live at /?build=<token>. Those links are public and
                # already shared, so keep them working by pointing at the new path.
                legacy_token = query.get("build", [""])[0]
                if legacy_token:
                    return self.redirect(f"/build/{validate_public_token(legacy_token)}")
                return self.serve_static("index.html", send_body=send_body)
            if path == "/about":
                return self.serve_static("about.html", send_body=send_body)
            if path.startswith("/build/"):
                # The permalink reuses index.html; app.js strips the form when the
                # path carries a token and renders the build panel only.
                validate_public_token(path.removeprefix("/build/"))
                return self.serve_static("index.html", send_body=send_body)
            if path.startswith("/static/"):
                return self.serve_static(path.removeprefix("/static/"), send_body=send_body)
            if path == "/api/devices":
                if not send_body:
                    return self.head_not_allowed()
                firmware_id = query.get("firmware", [""])[0]
                source = None
                gate_version = None
                platformio: dict[str, str | None] = {}
                if firmware_id:
                    # The boards of the selected firmware at the selected version.
                    version = resolve_supported_version(
                        self.config, query.get("tag", [""])[0] or None, firmware_id=firmware_id
                    )
                    source = get_firmware(self.config.root_dir, firmware_id)
                    gate_version = version["version"]
                    devices, platformio, from_firmware = catalog_for(self.config, source, version["sha"])
                    devices = [d for d in devices if exclusion_reason(d.platformio_env, d.family) is None]
                else:
                    # No firmware named: the static list, which also labels old builds.
                    devices, from_firmware = enabled_devices(self.config.root_dir), False
                return self.json_response(
                    {
                        "fromFirmware": from_firmware,
                        "devices": [device_json(device, source, gate_version, platformio) for device in devices],
                    }
                )
            if path in {"/api/health", "/health"}:
                return self.serve_health(send_body=send_body)
            if path == "/api/build-options":
                if not send_body:
                    return self.head_not_allowed()
                options = load_build_options(self.config.root_dir)
                # The page states the retention window next to the submit button.
                options["artifactTtlDays"] = self.config.artifact_ttl_days
                return self.json_response(options)
            if path == "/api/firmwares":
                if not send_body:
                    return self.head_not_allowed()
                default, firmwares = load_firmware_catalog(self.config.root_dir)
                return self.json_response(
                    {"default": default, "firmwares": [item.public() for item in firmwares]}
                )
            if path == "/api/firmware-versions":
                if not send_body:
                    return self.head_not_allowed()
                force_refresh = query.get("refresh", ["0"])[0] in {"1", "true", "yes"}
                firmware_id = query.get("firmware", [DEFAULT_FIRMWARE_ID])[0]
                versions = list_versions_with_refresh(
                    self.config, force_refresh=force_refresh, firmware_id=firmware_id
                )
                return self.json_response({"firmwareId": firmware_id, "versions": versions})
            if path == "/api/prefs-template":
                if not send_body:
                    return self.head_not_allowed()
                firmware_id = query.get("firmware", [DEFAULT_FIRMWARE_ID])[0]
                tag = query.get("tag", [""])[0]
                version = resolve_supported_version(self.config, tag, firmware_id=firmware_id)
                ref = version["sha"] if version["branch"] else version["tag"]
                return self.text_response(
                    get_userprefs_template(self.config, version["tag"], firmware_id=firmware_id, ref=ref),
                    "text/plain",
                )
            if path.startswith("/api/builds/"):
                if not send_body:
                    return self.head_not_allowed()
                token = validate_public_token(path.removeprefix("/api/builds/"))
                row = get_build_by_token(self.config, token)
                if row is None:
                    return self.error_response(HTTPStatus.NOT_FOUND, "Build no encontrado.")
                return self.json_response({"build": public_build_view(row), "queue": queue_view(self.config, row)})
            if path.startswith("/download/"):
                token = validate_public_token(path.removeprefix("/download/"))
                return self.serve_download(token, send_body=send_body)

            return self.error_response(HTTPStatus.NOT_FOUND, "Ruta no encontrada.")
        except FirmwareLookupError as exc:
            return self.error_response(HTTPStatus.BAD_GATEWAY, str(exc))
        except ValueError as exc:
            return self.error_response(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:  # noqa: BLE001
            return self.error_response(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error interno: {exc}")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/builds":
                self.enforce_rate_limit()
                payload = self.read_json_body()
                submission = create_build_submission(self.config, payload)
                return self.json_response(
                    {
                        "build": submission["public"],
                        "queue": queue_view(self.config, submission["row"]),
                        "buildUrl": submission["buildUrl"],
                        "statusUrl": submission["statusUrl"],
                        "downloadUrl": submission["downloadUrl"],
                    },
                    status=HTTPStatus.CREATED,
                )
            return self.error_response(HTTPStatus.NOT_FOUND, "Ruta no encontrada.")
        except (ValueError, JsoncValidationError, FirmwareLookupError) as exc:
            return self.error_response(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:  # noqa: BLE001
            return self.error_response(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error interno: {exc}")

    def client_ip(self) -> str:
        if self.config.trust_proxy:
            forwarded = self.headers.get("X-Forwarded-For", "")
            first_hop = forwarded.split(",")[0].strip()
            if first_hop:
                return first_hop
        return self.client_address[0]

    def enforce_rate_limit(self) -> None:
        ip = self.client_ip()
        now = time.time()
        window_start = now - 300
        entries = [entry for entry in RATE_LIMIT.get(ip, []) if entry >= window_start]
        if len(entries) >= 10:
            raise ValueError("Demasiadas solicitudes. Intentalo de nuevo en unos minutos.")
        entries.append(now)
        RATE_LIMIT[ip] = entries

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 200000:
            raise ValueError("Cuerpo de peticion invalido.")
        raw = self.rfile.read(length).decode("utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("La peticion debe ser un objeto JSON.")
        return payload

    def serve_health(self, *, send_body: bool = True) -> None:
        """Public liveness probe. Touches the database so it fails when the queue does."""
        try:
            stats = build_stats(self.config)
        except Exception:  # noqa: BLE001
            # The reason could name paths or SQL, and this endpoint is public.
            payload = {"status": "error", "database": "unavailable"}
            status = HTTPStatus.SERVICE_UNAVAILABLE
        else:
            payload = {"status": "ok", "builds": stats}
            status = HTTPStatus.OK
        if not send_body:
            body_length = len(json.dumps(payload, default=_json_default).encode("utf-8"))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(body_length))
            self.end_headers()
            return
        return self.json_response(payload, status=status)

    def serve_static(self, relative_name: str, *, send_body: bool = True) -> None:
        static_root = self.config.root_dir / "static"
        target = (static_root / relative_name).resolve()
        if not str(target).startswith(str(static_root.resolve())) or not target.exists() or not target.is_file():
            return self.error_response(HTTPStatus.NOT_FOUND, "Fichero no encontrado.")
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        if target.suffix == ".html":
            # The footer names the running version; filled in here so the pages
            # need no script or extra request for it.
            body = body.replace(VERSION_PLACEHOLDER, __version__.encode("ascii"))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Without this browsers keep serving a redeployed page from cache, and phones
        # are the worst offenders. These files are a few KB, so always revalidate.
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def serve_download(self, token: str, *, send_body: bool = True) -> None:
        row = get_build_by_token(self.config, token)
        if row is None or row["status"] not in {"succeeded", "expired"}:
            return self.error_response(HTTPStatus.NOT_FOUND, "Artefacto no disponible.")
        if row["status"] == "expired":
            return self.error_response(HTTPStatus.GONE, "Artefacto expirado.")
        if build_is_expired(row):
            expire_build_artifact(self.config, row)
            return self.error_response(HTTPStatus.GONE, "Artefacto expirado.")
        artifact_path = row["artifact_path"]
        if not artifact_path:
            return self.error_response(HTTPStatus.NOT_FOUND, "Artefacto no disponible.")
        path = Path(artifact_path)
        if not path.exists() or not path.is_file():
            return self.error_response(HTTPStatus.GONE, "Artefacto no encontrado en disco.")

        firmware_id = row.get("firmware_id") or DEFAULT_FIRMWARE_ID
        # A branch build names its commit: the branch name says nothing about what was compiled.
        label = row["firmware_tag"]
        if firmware_id != DEFAULT_FIRMWARE_ID and row.get("firmware_version") and label == firmware_id:
            label = f"{row['firmware_version']}-{str(row['firmware_sha'])[:7]}"
        filename = f"{firmware_id}-{label}-{row['platformio_env']}-{token[:8]}.zip"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        if send_body:
            with path.open("rb") as fh:
                self.wfile.write(fh.read())

    def json_response(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def text_response(self, body_text: str, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = body_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location: str, status: HTTPStatus = HTTPStatus.MOVED_PERMANENTLY) -> None:
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def error_response(self, status: HTTPStatus, message: str) -> None:
        self.json_response(_public_error(message), status=status)

    def head_not_allowed(self) -> None:
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self.send_header("Allow", "GET")
        self.send_header("Content-Length", "0")
        self.end_headers()


def run_server(config: Config | None = None) -> None:
    config = config or load_config()
    ensure_directories(config)
    initialize_database(config)
    MeshtasticBuilderHandler.config = config
    server = ThreadingHTTPServer((config.host, config.port), MeshtasticBuilderHandler)
    print(f"Meshtastic Builder listening on http://{config.host}:{config.port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
