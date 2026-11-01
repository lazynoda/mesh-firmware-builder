"""Queue position and time estimates for the build page.

One worker builds one firmware at a time, in `created_at, id` order (see
`claim_next_build`). So a queued build waits for whatever is running plus every
build queued before it, and each of those takes about as long as that board
took the last few times. Build time depends on the board (chip family, whether
its libraries are prewarmed), not on the firmware, so the estimate is keyed by
PlatformIO environment.

Only counts and times leave this module: never which boards or whose builds are
ahead.
"""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any, Iterable

from .config import Config
from .db import connection, initialize_database, parse_iso, utc_now
from .devices import load_devices

# Most recent successful builds of one board that feed its estimate. A short
# window lets a builder change (CPU limit, a cache) show up within a few builds.
SAMPLE_SIZE = 10
# Successful builds read per request. The table is small; this only caps it.
HISTORY_LIMIT = 500
# Used when this instance has never finished a build.
DEFAULT_SECONDS = 15 * 60
# A running build past this multiple of its estimate is probably stuck, so the
# times of the builds queued behind it would be fiction.
STALL_FACTOR = 2
# Builds queued with nothing running for this long mean the worker is not
# consuming the queue (it polls every few seconds).
WORKER_IDLE_SECONDS = 300


def _seconds_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        seconds = (parse_iso(end) - parse_iso(start)).total_seconds()
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


class Estimator:
    """Median build time per board, falling back to the chip family, then to
    every board, then to a fixed default."""

    def __init__(self, history: Iterable[tuple[str, float]], families: dict[str, str]):
        self.families = families
        self.by_env: dict[str, list[float]] = {}
        self.by_family: dict[str, list[float]] = {}
        self.overall: list[float] = []
        # `history` is newest first, so each list keeps the latest samples.
        for env, seconds in history:
            env_samples = self.by_env.setdefault(env, [])
            if len(env_samples) < SAMPLE_SIZE:
                env_samples.append(seconds)
            family = families.get(env)
            if family:
                family_samples = self.by_family.setdefault(family, [])
                if len(family_samples) < SAMPLE_SIZE * 3:
                    family_samples.append(seconds)
            if len(self.overall) < SAMPLE_SIZE * 5:
                self.overall.append(seconds)

    def estimate(self, env: str) -> tuple[int, str]:
        """Seconds a build of `env` is expected to take, and what it is based on."""
        if self.by_env.get(env):
            return round(statistics.median(self.by_env[env])), "board"
        family = self.families.get(env)
        if family and self.by_family.get(family):
            return round(statistics.median(self.by_family[family])), "family"
        if self.overall:
            return round(statistics.median(self.overall)), "all"
        return DEFAULT_SECONDS, "default"


def board_families(config: Config) -> dict[str, str]:
    """PlatformIO env -> chip family, from the static catalogue. Fork-only boards
    are missing from it and fall through to the overall estimate."""
    families: dict[str, str] = {}
    try:
        devices = load_devices(config.root_dir)
    except (OSError, ValueError, TypeError):
        return families
    for device in devices:
        families[device.platformio_env] = device.family
        if device.mui_env:
            families[device.mui_env] = device.family
    return families


def queue_view(
    config: Config,
    row: dict[str, Any],
    *,
    now: datetime | None = None,
    families: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Position and remaining time for a queued or running build, else None.

    Queued: `ahead` = builds the worker will finish first (the running one
    included); `remainingSeconds` = until this build is done, or None when the
    queue looks stuck. Running: `elapsedSeconds`, `remainingSeconds` (0 once
    past the estimate) and `overrun`.
    """
    status = row.get("status")
    if status not in ("queued", "running"):
        return None
    now = now or utc_now()
    families = board_families(config) if families is None else families
    initialize_database(config)
    with connection(config) as conn:
        active = conn.execute(
            """
            SELECT id, platformio_env, status, created_at, started_at
            FROM build_requests
            WHERE status IN ('queued', 'running')
            ORDER BY created_at ASC, id ASC
            """
        ).fetchall()
        history_rows = conn.execute(
            """
            SELECT platformio_env, started_at, finished_at
            FROM build_requests
            WHERE status IN ('succeeded', 'expired')
              AND started_at IS NOT NULL AND finished_at IS NOT NULL
            ORDER BY finished_at DESC, id DESC
            LIMIT ?
            """,
            (HISTORY_LIMIT,),
        ).fetchall()

    history = []
    for item in history_rows:
        seconds = _seconds_between(item["started_at"], item["finished_at"])
        if seconds is not None:
            history.append((item["platformio_env"], seconds))
    estimator = Estimator(history, families)
    own_estimate, basis = estimator.estimate(row["platformio_env"])

    def elapsed_since(start: str | None) -> float:
        if not start:
            return 0.0
        try:
            return max((now - parse_iso(start)).total_seconds(), 0.0)
        except (TypeError, ValueError):
            return 0.0

    if status == "running":
        elapsed = elapsed_since(row.get("started_at"))
        return {
            "ahead": 0,
            "estimateSeconds": own_estimate,
            "estimateBasis": basis,
            "elapsedSeconds": round(elapsed),
            "remainingSeconds": max(round(own_estimate - elapsed), 0),
            "overrun": elapsed > own_estimate,
        }

    own_key = (row["created_at"], row["id"])
    ahead = 0
    wait = 0.0
    stuck = False
    running_count = 0
    for item in active:
        if item["id"] == row["id"]:
            continue
        estimate, _ = estimator.estimate(item["platformio_env"])
        if item["status"] == "running":
            running_count += 1
            ahead += 1
            elapsed = elapsed_since(item["started_at"])
            if elapsed > STALL_FACTOR * estimate:
                stuck = True
            wait += max(estimate - elapsed, 0.0)
        elif (item["created_at"], item["id"]) < own_key:
            ahead += 1
            wait += estimate

    oldest_queued = next((item for item in active if item["status"] == "queued"), None)
    if running_count == 0 and oldest_queued is not None:
        if elapsed_since(oldest_queued["created_at"]) > WORKER_IDLE_SECONDS:
            stuck = True

    return {
        "ahead": ahead,
        "estimateSeconds": own_estimate,
        "estimateBasis": basis,
        "remainingSeconds": None if stuck else round(wait + own_estimate),
    }
