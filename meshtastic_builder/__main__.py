from __future__ import annotations

import argparse
from pathlib import Path

from .admin import (
    docker_status,
    print_build_log,
    print_versions,
    refresh_firmware_versions,
    set_firmware_supported,
    validate_devices_against_repo,
)
from .app import run_server
from .device_sync import run_sync
from .firmwares import list_firmwares
from .cleanup import expire_old_artifacts
from .db import initialize_database
from .config import load_config
from .worker import run_worker


def main() -> None:
    try:
        _dispatch()
    except ValueError as exc:
        # Operator mistakes - an unknown tag, an unknown build token - are not
        # bugs, so they get one line instead of a traceback.
        raise SystemExit(f"error: {exc}") from exc


def _dispatch() -> None:
    parser = argparse.ArgumentParser(prog="mesh-firmware-builder")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    sub.add_parser("init-db")
    sub.add_parser("cleanup")
    firmware_help = "Firmware id from data/firmwares.json (default: meshtastic)."
    refresh = sub.add_parser(
        "refresh-versions",
        help="Re-read tags (or the branch head) from GitHub. Every firmware unless --firmware is given.",
    )
    refresh.add_argument("--firmware", default=None, help="Firmware id from data/firmwares.json (default: all).")
    list_versions = sub.add_parser("list-versions")
    list_versions.add_argument("--all", action="store_true")
    list_versions.add_argument("--firmware", default="meshtastic", help=firmware_help)
    set_supported = sub.add_parser("set-supported")
    set_supported.add_argument("tag")
    set_supported.add_argument("--firmware", default="meshtastic", help=firmware_help)
    set_unsupported = sub.add_parser("set-unsupported")
    set_unsupported.add_argument("tag")
    set_unsupported.add_argument("--firmware", default="meshtastic", help=firmware_help)
    validate_devices = sub.add_parser("validate-devices")
    validate_devices.add_argument("repo_path")
    sync_devices = sub.add_parser(
        "sync-devices",
        help="Update data/devices.json from a firmware checkout (the Web Flasher's board set).",
    )
    sync_devices.add_argument("repo_path")
    sync_devices.add_argument("--write", action="store_true", help="Write the file; default is a dry run.")
    build_log = sub.add_parser("build-log")
    build_log.add_argument("token")
    build_log.add_argument("--full", action="store_true", help="Print the whole log, not the tail.")
    build_log.add_argument("--tail-lines", type=int, default=40)
    docker_status_parser = sub.add_parser("docker-status")
    docker_status_parser.add_argument("--timeout-seconds", type=int, default=10)
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = load_config()

    if args.command == "serve":
        run_server(config)
    elif args.command == "init-db":
        initialize_database(config)
    elif args.command == "cleanup":
        print(f"Expired {expire_old_artifacts(config)} artifact(s).")
    elif args.command == "refresh-versions":
        ids = [args.firmware] if args.firmware else [item.id for item in list_firmwares(config.root_dir)]
        failed = False
        for firmware_id in ids:
            # One firmware failing (GitHub hiccup, renamed repo) must not stop the others.
            try:
                versions = refresh_firmware_versions(config, firmware_id)
            except Exception as exc:  # noqa: BLE001 - operator command, report and go on
                print(f"{firmware_id}: refresh failed: {exc}")
                failed = True
                continue
            print(f"{firmware_id}: refreshed {len(versions)} version(s).")
        if failed:
            raise SystemExit(1)
    elif args.command == "list-versions":
        print_versions(config, include_unsupported=args.all, firmware_id=args.firmware)
    elif args.command == "set-supported":
        item = set_firmware_supported(config, args.tag, True, firmware_id=args.firmware)
        print(f"{item['tag']} supported=1")
    elif args.command == "set-unsupported":
        item = set_firmware_supported(config, args.tag, False, firmware_id=args.firmware)
        print(f"{item['tag']} supported=0")
    elif args.command == "validate-devices":
        results = validate_devices_against_repo(config, Path(args.repo_path))
        invalid = False
        for item in results:
            status = "OK" if item["valid"] else "MISSING"
            print(f"{status}\t{item['device_id']}\t{item['platformio_env']}\t{item['definition'] or ''}")
            invalid = invalid or not bool(item["valid"])
        if invalid:
            raise SystemExit(1)
    elif args.command == "sync-devices":
        run_sync(config.root_dir, Path(args.repo_path), write=args.write)
    elif args.command == "build-log":
        print_build_log(config, args.token, tail_lines=args.tail_lines, full=args.full)
    elif args.command == "docker-status":
        status = docker_status(config, timeout_seconds=args.timeout_seconds)
        print("OK" if status["ok"] else "ERROR")
        if status["error"]:
            print(status["error"])
        if status["stderr"]:
            print(str(status["stderr"]).strip())
        if not status["ok"]:
            raise SystemExit(1)
    elif args.command == "worker":
        run_worker(config, once=args.once)


if __name__ == "__main__":
    main()
