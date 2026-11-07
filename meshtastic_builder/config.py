from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _path_env(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser()


@dataclass(frozen=True)
class Config:
    root_dir: Path
    data_dir: Path
    db_path: Path
    artifact_dir: Path
    job_dir: Path
    cache_dir: Path
    host: str
    port: int
    base_url: str
    trust_proxy: bool
    github_tags_url: str
    github_max_tag_pages: int
    auto_support_latest_tags: int
    raw_userprefs_url: str
    max_prefs_bytes: int
    artifact_ttl_days: int
    build_timeout_seconds: int
    stale_running_seconds: int
    builder_image: str
    builder_mode: str
    docker_binary: str
    docker_network: str
    docker_transport: str
    docker_cpus: str
    docker_memory: str
    docker_pids_limit: int
    ccache_volume: str = ""
    ccache_maxsize: str = "20G"


def load_config() -> Config:
    root_dir = Path(__file__).resolve().parent.parent
    data_dir = _path_env("MB_DATA_DIR", str(root_dir / "var"))
    db_path = _path_env("MB_DB_PATH", str(data_dir / "meshtastic-builder.sqlite"))
    artifact_dir = _path_env("MB_ARTIFACT_DIR", str(data_dir / "artifacts"))
    job_dir = _path_env("MB_JOB_DIR", str(data_dir / "jobs"))
    cache_dir = _path_env("MB_CACHE_DIR", str(data_dir / "cache"))

    return Config(
        root_dir=root_dir,
        data_dir=data_dir,
        db_path=db_path,
        artifact_dir=artifact_dir,
        job_dir=job_dir,
        cache_dir=cache_dir,
        host=os.getenv("MB_HOST", "127.0.0.1"),
        port=int(os.getenv("MB_PORT", "8080")),
        base_url=os.getenv("MB_BASE_URL", "http://localhost:8080").rstrip("/"),
        trust_proxy=_bool_env("MB_TRUST_PROXY", False),
        github_tags_url=os.getenv(
            "MB_GITHUB_TAGS_URL",
            "https://api.github.com/repos/meshtastic/firmware/tags?per_page=100",
        ),
        github_max_tag_pages=int(os.getenv("MB_GITHUB_MAX_TAG_PAGES", "20")),
        auto_support_latest_tags=int(os.getenv("MB_AUTO_SUPPORT_LATEST_TAGS", "20")),
        raw_userprefs_url=os.getenv(
            "MB_RAW_USERPREFS_URL",
            "https://raw.githubusercontent.com/meshtastic/firmware/{tag}/userPrefs.jsonc",
        ),
        max_prefs_bytes=int(os.getenv("MB_MAX_PREFS_BYTES", "65536")),
        artifact_ttl_days=int(os.getenv("MB_ARTIFACT_TTL_DAYS", "7")),
        build_timeout_seconds=int(os.getenv("MB_BUILD_TIMEOUT_SECONDS", "3600")),
        stale_running_seconds=int(os.getenv("MB_STALE_RUNNING_SECONDS", "7200")),
        builder_image=os.getenv("MB_BUILDER_IMAGE", "meshtastic-firmware-builder:local"),
        builder_mode=os.getenv("MB_BUILDER_MODE", "docker"),
        docker_binary=os.getenv("MB_DOCKER_BINARY", "docker"),
        docker_network=os.getenv("MB_DOCKER_NETWORK", "bridge"),
        docker_transport=os.getenv("MB_DOCKER_TRANSPORT", "auto"),
        docker_cpus=os.getenv("MB_DOCKER_CPUS", "4"),
        docker_memory=os.getenv("MB_DOCKER_MEMORY", "4g"),
        docker_pids_limit=int(os.getenv("MB_DOCKER_PIDS_LIMIT", "512")),
        ccache_volume=os.getenv("MB_CCACHE_VOLUME", "").strip(),
        ccache_maxsize=os.getenv("MB_CCACHE_MAXSIZE", "20G").strip(),
    )


def ensure_directories(config: Config) -> None:
    for path in (
        config.data_dir,
        config.artifact_dir,
        config.job_dir,
        config.cache_dir,
        config.db_path.parent,
    ):
        path.mkdir(parents=True, exist_ok=True)
