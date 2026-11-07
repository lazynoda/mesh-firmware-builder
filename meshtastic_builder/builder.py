from __future__ import annotations

import hashlib
import os
import re
import sys
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .build_failures import (
    CODE_INFRASTRUCTURE,
    CODE_NO_ARTIFACTS,
    CODE_TIMEOUT,
    BuildFailure,
    classify_build_log,
)
from .code_options import code_options_need_patch, fixed_gps_patch_needed, load_build_options
from .config import Config
from .db import iso_now
from .firmwares import DEFAULT_FIRMWARE_ID, FirmwareSource, get_firmware
from .jsonc import extract_userpref_keys, prefs_for_compiler


PATCH_RELATIVE_PATH = Path("docker") / "patches" / "userprefs-ext.patch"

# The builder container applies every patch dropped in this subdirectory of the
# input mount, in name order. A subdirectory, not the input root, so the glob
# can never pick up userPrefs.jsonc or BUILD_INFO.txt.
PATCH_INPUT_DIR = "patches"

# Present in every container runtime we target. Used to tell whether this process
# shares a filesystem namespace with the Docker daemon.
CONTAINER_MARKER = Path("/.dockerenv")


@dataclass(frozen=True)
class BuildArtifact:
    path: Path
    sha256: str
    size_bytes: int
    log: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_firmware_source(config: Config, build: dict[str, object]) -> FirmwareSource:
    """The repository this build compiles. Rows from before the selector are upstream's."""
    return get_firmware(config.root_dir, str(build.get("firmware_id") or DEFAULT_FIRMWARE_ID))


def gate_version(build: dict[str, object]) -> str:
    """x.y.z for the version gates: stored at submit time, the tag on older rows."""
    return str(build.get("firmware_version") or build["firmware_tag"])


def build_info(build: dict[str, object], source: FirmwareSource) -> str:
    return "\n".join(
        [
            "Meshtastic Builder Artifact",
            f"created_at={iso_now()}",
            f"build_token={build['public_token']}",
            f"device_id={build['device_id']}",
            f"platformio_env={build['platformio_env']}",
            f"firmware={source.name}",
            f"firmware_tag={build['firmware_tag']}",
            f"firmware_sha={build['firmware_sha']}",
            f"firmware_version={gate_version(build)}",
            f"code_options={build.get('code_options') or 'none'}",
            f"source={source.url}",
            f"license={source.license}",
            "",
        ]
    )


def run_build(config: Config, build: dict[str, object]) -> BuildArtifact:
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    token = str(build["public_token"])
    final_zip = config.artifact_dir / f"{token}.zip"
    job_root = config.job_dir / token
    input_dir = job_root / "input"
    output_dir = job_root / "output"

    if job_root.exists():
        shutil.rmtree(job_root)
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    # The stored prefs stay as the user wrote them; only the copy the compiler reads is
    # shell-escaped (see jsonc.shell_escape_for_compiler). The ZIP ships this copy, so
    # rebuilding from it with upstream PlatformIO gives the same firmware.
    (input_dir / "userPrefs.jsonc").write_text(prefs_for_compiler(str(build["prefs_jsonc"])), encoding="utf-8")
    source = build_firmware_source(config, build)
    (input_dir / "BUILD_INFO.txt").write_text(build_info(build, source), encoding="utf-8")
    stage_patches(config, build, input_dir)

    try:
        if config.builder_mode == "fake":
            log = run_fake_build(build, input_dir, final_zip)
        else:
            log = run_docker_build(config, build, input_dir, output_dir, final_zip, source)
        return BuildArtifact(
            path=final_zip,
            sha256=sha256_file(final_zip),
            size_bytes=final_zip.stat().st_size,
            log=log,
        )
    finally:
        if job_root.exists():
            shutil.rmtree(job_root, ignore_errors=True)


def stage_patches(config: Config, build: dict[str, object], input_dir: Path) -> list[str]:
    """Copy the firmware patches this build needs into the container input.

    Two independent reasons to patch, each with its own firmware window:

    - userprefs-ext: below 2.8.0 the firmware ignores the advanced-option macros,
      so the build only honours them once the patch teaches installDefaultConfig
      to read them. From 2.8.0 the firmware reads them itself.
    - fixed-gps-nodedb: from 2.8.0 the fixed-position block fails to compile
      upstream. Below 2.8.0 it compiles as shipped and must be left alone.

    Users never supply patch content; only these repo-controlled files are ever
    staged. Returns the staged file names, for the build log.
    """
    options = load_build_options(config.root_dir)
    firmware_tag = gate_version(build)
    wanted: list[Path] = []

    if build.get("code_options") and code_options_need_patch(options, firmware_tag):
        wanted.append(config.root_dir / PATCH_RELATIVE_PATH)

    pref_keys = extract_userpref_keys(str(build["prefs_jsonc"]))
    if fixed_gps_patch_needed(options, firmware_tag, pref_keys):
        wanted.append(config.root_dir / str(options["fixedGpsPatch"]["patchFile"]))

    if not wanted:
        return []

    patch_dir = input_dir / PATCH_INPUT_DIR
    patch_dir.mkdir(parents=True, exist_ok=True)
    staged: list[str] = []
    for patch in wanted:
        if not patch.is_file():
            raise BuildFailure(
                CODE_INFRASTRUCTURE,
                phase="patches",
                detail=f"Missing firmware patch {patch.name} in the builder image.",
            )
        shutil.copyfile(patch, patch_dir / patch.name)
        staged.append(patch.name)
    return staged


def run_fake_build(build: dict[str, object], input_dir: Path, final_zip: Path) -> str:
    with zipfile.ZipFile(final_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(input_dir / "BUILD_INFO.txt", "BUILD_INFO.txt")
        zf.write(input_dir / "userPrefs.jsonc", "userPrefs.jsonc")
        zf.writestr(
            f"firmware-{build['platformio_env']}.txt",
            "Fake firmware artifact for local queue testing.\n",
        )
    return "Fake builder mode completed successfully."


def run_docker_build(
    config: Config,
    build: dict[str, object],
    input_dir: Path,
    output_dir: Path,
    final_zip: Path,
    source: FirmwareSource | None = None,
) -> str:
    source = source or build_firmware_source(config, build)
    transport = docker_transport(config)
    if transport == "copy":
        return run_docker_build_copy(config, build, input_dir, output_dir, final_zip, source)
    if transport != "bind":
        raise BuildFailure(
            CODE_INFRASTRUCTURE,
            phase="setup",
            detail=f"Unsupported Docker transport: {config.docker_transport}",
        )
    return run_docker_build_bind(config, build, input_dir, output_dir, final_zip, source)


def builder_args(build: dict[str, object], source: FirmwareSource) -> list[str]:
    """Positional arguments of build-firmware: tag, commit, env and the repository to fetch from."""
    return [
        str(build["firmware_tag"]),
        str(build["firmware_sha"]),
        str(build["platformio_env"]),
        source.clone_url,
    ]


def section(title: str, body: str) -> str:
    """One labelled block of the build log, so the phases stay findable by eye."""
    return f"\n===== {title} =====\n{body.strip()}\n"


def run_step(
    command: list[str],
    *,
    config: Config,
    phase: str,
    timeout: int,
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run one docker step, returning it with its output already labelled."""
    try:
        proc = subprocess.run(
            command,
            cwd=str(config.root_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BuildFailure(
            CODE_TIMEOUT,
            phase=phase,
            detail=f"Step timed out after {timeout}s.",
            log=section(phase, _decode(exc.stdout) + _decode(exc.stderr)),
        ) from exc
    body = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc, section(phase, body)


def _decode(stream: object) -> str:
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", "replace")
    return str(stream)


def raise_build_failure(returncode: int, log: str) -> None:
    """Name what killed the build, instead of handing 4 KB of PlatformIO to a user."""
    code, phase, detail = classify_build_log(log)
    if not detail:
        detail = f"The builder exited with code {returncode}."
    raise BuildFailure(code, phase=phase or "build", detail=detail, log=log)


def docker_transport(config: Config) -> str:
    """Pick the transport that can actually hand the job inputs to the daemon.

    Bind only works when the daemon resolves our paths in our own filesystem.
    A remote DOCKER_HOST breaks that, and so does running this worker in a
    container that reaches the host daemon through a mounted socket: the daemon
    resolves /data/jobs/<token>/input against the host, silently creates it
    empty, and the builder dies on a missing userPrefs.jsonc.
    """
    configured = config.docker_transport.strip().lower()
    if configured != "auto":
        return configured
    docker_host = os.getenv("DOCKER_HOST", "").strip().lower()
    if docker_host.startswith(("ssh://", "tcp://", "http://", "https://")):
        return "copy"
    if CONTAINER_MARKER.exists():
        return "copy"
    return "bind"


# There is deliberately no PlatformIO build cache here. `build_cache_dir` is a
# SCons CacheDir, and SCons does not run a target's post-actions when it
# retrieves that target from the cache. Meshtastic generates its flashable
# images inside post-actions - extra_scripts/nrf52_extra.py hangs the .uf2 off
# `$BUILD_DIR/${PROGNAME}.hex`, extra_scripts/esp32_extra.py hangs the
# .factory.bin off `$BUILD_DIR/${PROGNAME}.bin` - and those files are side
# effects, not declared targets, so they are never cached and never regenerated.
# A fully cached build therefore succeeds and ships a ZIP with nothing flashable
# in it. Reproduced on nrf52_promicro_diy_tcxo: 15s build, .elf/.hex/.zip
# present, no .uf2.
#
# The speed comes from ccache instead (ccache_docker_args): it caches each
# object file below SCons, so every target and every post-action still runs.

CCACHE_MOUNT = "/ccache"
# A Docker named volume, never a host path: the daemon may be remote or rootless,
# where a host path would resolve somewhere else (or nowhere).
VOLUME_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
CCACHE_VOLUME_RE = VOLUME_NAME_RE
# ccache's own size syntax: a number with an optional k/M/G/T suffix (Ki/Mi/Gi/Ti
# for powers of two). Anything else would make ccache refuse every call.
CCACHE_MAXSIZE_RE = re.compile(r"[0-9]+(\.[0-9]+)?([kKMGT]i?)?")


def ccache_docker_args(config: Config) -> list[str]:
    """Mount the shared compiler cache into the builder, or nothing when it is off.

    Off when MB_CCACHE_VOLUME is empty. A malformed volume name or size also
    turns it off rather than failing builds: the cache only ever buys speed.
    """
    volume = config.ccache_volume.strip()
    maxsize = config.ccache_maxsize.strip()
    if not volume:
        return []
    if not CCACHE_VOLUME_RE.fullmatch(volume):
        print(f"MB_CCACHE_VOLUME {volume!r} is not a Docker volume name; building without ccache.", file=sys.stderr)
        return []
    if not CCACHE_MAXSIZE_RE.fullmatch(maxsize):
        print(f"MB_CCACHE_MAXSIZE {maxsize!r} is not a ccache size; building without ccache.", file=sys.stderr)
        return []
    return [
        "-v",
        f"{volume}:{CCACHE_MOUNT}",
        "-e",
        f"CCACHE_DIR={CCACHE_MOUNT}",
        "-e",
        f"CCACHE_MAXSIZE={maxsize}",
    ]


# PlatformIO's download store: the package archives exactly as fetched (platforms,
# toolchains, frameworks, libraries), kept by URL + checksum. Shared on purpose
# instead of the installed packages: ESP32 builds rewrite their installed
# framework for their own board (custom_sdkconfig), so a shared install would
# hand one board's rebuilt libraries to the next. Archives are only ever read and
# unpacked into the build's own container, which is thrown away afterwards.
PIO_DOWNLOAD_MOUNT = "/pio-downloads"


def pio_download_docker_args(config: Config) -> list[str]:
    """Mount the shared PlatformIO download store, or nothing when it is off."""
    volume = config.pio_download_volume.strip()
    if not volume:
        return []
    if not VOLUME_NAME_RE.fullmatch(volume):
        print(
            f"MB_PIO_DOWNLOAD_VOLUME {volume!r} is not a Docker volume name; downloading packages per build.",
            file=sys.stderr,
        )
        return []
    return ["-v", f"{volume}:{PIO_DOWNLOAD_MOUNT}", "-e", f"MB_PIO_DOWNLOAD_DIR={PIO_DOWNLOAD_MOUNT}"]


def cache_docker_args(config: Config) -> list[str]:
    """Every shared cache a builder container mounts."""
    return [*ccache_docker_args(config), *pio_download_docker_args(config)]


def package_output(output_dir: Path, final_zip: Path, log: str) -> str:
    """Take the builder's zip, or make one, and fail by name when there is nothing."""
    zip_candidates = sorted(output_dir.glob("*.zip"), key=lambda path: path.stat().st_mtime, reverse=True)
    if zip_candidates:
        shutil.copy2(zip_candidates[0], final_zip)
        return log

    files = [path for path in output_dir.rglob("*") if path.is_file()]
    if not files:
        raise BuildFailure(
            CODE_NO_ARTIFACTS,
            phase="package",
            detail="The build finished but produced no firmware files.",
            log=log,
        )
    with zipfile.ZipFile(final_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, path.relative_to(output_dir))
    return log + section("package", "Packaged output directory because builder did not emit a zip.")


def run_docker_build_bind(
    config: Config,
    build: dict[str, object],
    input_dir: Path,
    output_dir: Path,
    final_zip: Path,
    source: FirmwareSource,
) -> str:
    command = [
        config.docker_binary,
        "run",
        "--rm",
        "--network",
        config.docker_network,
        "--cpus",
        config.docker_cpus,
        "--memory",
        config.docker_memory,
        "--pids-limit",
        str(config.docker_pids_limit),
        "-v",
        f"{input_dir.resolve()}:/work/input:ro",
        "-v",
        f"{output_dir.resolve()}:/work/output",
        *cache_docker_args(config),
        config.builder_image,
        *builder_args(build, source),
    ]
    proc, log = run_step(command, config=config, phase="build", timeout=config.build_timeout_seconds)
    if proc.returncode != 0:
        raise_build_failure(proc.returncode, log)
    return package_output(output_dir, final_zip, log)


def run_docker_build_copy(
    config: Config,
    build: dict[str, object],
    input_dir: Path,
    output_dir: Path,
    final_zip: Path,
    source: FirmwareSource,
) -> str:
    create_command = [
        config.docker_binary,
        "create",
        "--network",
        config.docker_network,
        "--cpus",
        config.docker_cpus,
        "--memory",
        config.docker_memory,
        "--pids-limit",
        str(config.docker_pids_limit),
        *cache_docker_args(config),
        config.builder_image,
        *builder_args(build, source),
    ]
    create_proc, create_log = run_step(create_command, config=config, phase="create", timeout=120)
    if create_proc.returncode != 0:
        raise BuildFailure(
            CODE_INFRASTRUCTURE,
            phase="create",
            detail=f"Could not create the builder container (exit {create_proc.returncode}).",
            log=create_log,
        )
    container_id = (create_proc.stdout or "").strip().splitlines()[-1].strip()
    if not container_id:
        raise BuildFailure(
            CODE_INFRASTRUCTURE,
            phase="create",
            detail="Docker container creation did not return a container id.",
            log=create_log,
        )

    logs = [create_log]
    try:
        copy_input, copy_log = run_step(
            [config.docker_binary, "cp", f"{input_dir.resolve()}/.", f"{container_id}:/work/input"],
            config=config,
            phase="copy-input",
            timeout=120,
        )
        logs.append(copy_log)
        if copy_input.returncode != 0:
            raise BuildFailure(
                CODE_INFRASTRUCTURE,
                phase="copy-input",
                detail=f"Could not copy the build inputs into the container (exit {copy_input.returncode}).",
                log="".join(logs),
            )

        start_proc, start_log = run_step(
            [config.docker_binary, "start", "-a", container_id],
            config=config,
            phase="build",
            timeout=config.build_timeout_seconds,
        )
        logs.append(start_log)
        if start_proc.returncode != 0:
            raise_build_failure(start_proc.returncode, "".join(logs))

        copy_output, output_log = run_step(
            [config.docker_binary, "cp", f"{container_id}:/work/output/.", str(output_dir.resolve())],
            config=config,
            phase="copy-output",
            timeout=120,
        )
        logs.append(output_log)
        if copy_output.returncode != 0:
            raise BuildFailure(
                CODE_INFRASTRUCTURE,
                phase="copy-output",
                detail=f"Could not copy the build output out of the container (exit {copy_output.returncode}).",
                log="".join(logs),
            )

        return package_output(output_dir, final_zip, "".join(logs))
    finally:
        subprocess.run(
            [config.docker_binary, "rm", "-f", container_id],
            cwd=str(config.root_dir),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
