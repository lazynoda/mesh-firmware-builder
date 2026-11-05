from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Iterator
from typing import Any

from .config import Config, ensure_directories, load_config
from .security import generate_public_token


STATUS_ORDER = ("queued", "running", "succeeded", "failed", "expired")
STATUSES = set(STATUS_ORDER)


FIRMWARE_VERSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS firmware_versions (
  firmware_id TEXT NOT NULL DEFAULT 'meshtastic',
  tag TEXT NOT NULL,
  sha TEXT NOT NULL,
  release_name TEXT,
  published_at TEXT,
  supported INTEGER NOT NULL DEFAULT 1,
  smoke_test_status TEXT NOT NULL DEFAULT 'untested',
  last_checked_at TEXT NOT NULL,
  revoked INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (firmware_id, tag)
);
"""

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
""" + FIRMWARE_VERSIONS_TABLE + """
CREATE TABLE IF NOT EXISTS build_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  public_token TEXT NOT NULL UNIQUE,
  device_id TEXT NOT NULL,
  platformio_env TEXT NOT NULL,
  firmware_tag TEXT NOT NULL,
  firmware_sha TEXT NOT NULL,
  prefs_jsonc TEXT NOT NULL,
  prefs_hash TEXT NOT NULL,
  code_options TEXT,
  firmware_id TEXT NOT NULL DEFAULT 'meshtastic',
  firmware_version TEXT,
  device_label TEXT,
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'expired')),
  attempts INTEGER NOT NULL DEFAULT 0,
  artifact_path TEXT,
  artifact_sha256 TEXT,
  artifact_size_bytes INTEGER,
  error_message TEXT,
  error_code TEXT,
  build_log TEXT,
  worker_id TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  expires_at TEXT
);

-- The boards one commit of one firmware offers. Written once per commit: a
-- commit never changes, so there is nothing to refresh.
CREATE TABLE IF NOT EXISTS board_catalogs (
  firmware_id TEXT NOT NULL,
  sha TEXT NOT NULL,
  devices_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (firmware_id, sha)
);

CREATE INDEX IF NOT EXISTS idx_build_requests_status_created
  ON build_requests(status, created_at);

CREATE INDEX IF NOT EXISTS idx_build_requests_expires
  ON build_requests(status, expires_at);
"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_now() -> str:
    return utc_now().isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def connect(config: Config | None = None) -> sqlite3.Connection:
    config = config or load_config()
    ensure_directories(config)
    conn = sqlite3.connect(config.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def connection(config: Config | None = None) -> Iterator[sqlite3.Connection]:
    with closing(connect(config)) as conn:
        with conn:
            yield conn


def _migrate_firmware_versions(conn: sqlite3.Connection) -> None:
    """Key the tag cache by firmware as well as tag.

    The table used to hold upstream Meshtastic tags only, keyed by tag. Other
    firmwares have their own tags (and may reuse a name), so the key is now
    (firmware_id, tag). SQLite cannot change a primary key in place: rebuild
    the table and carry the existing rows over as upstream's.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(firmware_versions)")}
    if not columns or "firmware_id" in columns:
        return
    # One transaction, so a crash halfway leaves the old table in place.
    conn.execute("BEGIN")
    conn.execute("ALTER TABLE firmware_versions RENAME TO firmware_versions_legacy")
    conn.execute(FIRMWARE_VERSIONS_TABLE)
    conn.execute(
        """
        INSERT INTO firmware_versions
          (firmware_id, tag, sha, release_name, published_at, supported, smoke_test_status, last_checked_at)
        SELECT 'meshtastic', tag, sha, release_name, published_at, supported, smoke_test_status, last_checked_at
        FROM firmware_versions_legacy
        ORDER BY rowid ASC
        """
    )
    conn.execute("DROP TABLE firmware_versions_legacy")


def initialize_database(config: Config | None = None) -> None:
    config = config or load_config()
    ensure_directories(config)
    with connection(config) as conn:
        _migrate_firmware_versions(conn)
        conn.executescript(SCHEMA)
        version_columns = {row[1] for row in conn.execute("PRAGMA table_info(firmware_versions)")}
        if "revoked" not in version_columns:
            conn.execute("ALTER TABLE firmware_versions ADD COLUMN revoked INTEGER NOT NULL DEFAULT 0")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(build_requests)")}
        if "code_options" not in columns:
            conn.execute("ALTER TABLE build_requests ADD COLUMN code_options TEXT")
        if "error_code" not in columns:
            conn.execute("ALTER TABLE build_requests ADD COLUMN error_code TEXT")
        if "firmware_id" not in columns:
            conn.execute(
                "ALTER TABLE build_requests ADD COLUMN firmware_id TEXT NOT NULL DEFAULT 'meshtastic'"
            )
        if "firmware_version" not in columns:
            conn.execute("ALTER TABLE build_requests ADD COLUMN firmware_version TEXT")
        if "device_label" not in columns:
            conn.execute("ALTER TABLE build_requests ADD COLUMN device_label TEXT")
        if "email" in columns:
            try:
                conn.execute("ALTER TABLE build_requests DROP COLUMN email")
            except sqlite3.OperationalError:
                # DROP COLUMN needs SQLite >= 3.35. On older engines the column
                # simply stays; it is unused and nullable inserts never touch it.
                print("Could not drop the legacy email column; SQLite is too old. Leaving it in place.")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def hash_prefs(prefs_jsonc: str) -> str:
    return hashlib.sha256(prefs_jsonc.encode("utf-8")).hexdigest()


def upsert_firmware_versions(
    config: Config,
    versions: list[dict[str, Any]],
    firmware_id: str = "meshtastic",
) -> None:
    initialize_database(config)
    checked_at = iso_now()
    with connection(config) as conn:
        conn.executemany(
            """
            INSERT INTO firmware_versions
              (firmware_id, tag, sha, release_name, published_at, supported, smoke_test_status, last_checked_at,
               revoked)
            VALUES
              (:firmware_id, :tag, :sha, :release_name, :published_at, :supported, :smoke_test_status,
               :last_checked_at, :revoked)
            ON CONFLICT(firmware_id, tag) DO UPDATE SET
              sha = excluded.sha,
              release_name = excluded.release_name,
              published_at = excluded.published_at,
              last_checked_at = excluded.last_checked_at,
              revoked = excluded.revoked
            """,
            [
                {
                    "firmware_id": firmware_id,
                    "tag": item["tag"],
                    "sha": item["sha"],
                    "release_name": item.get("release_name") or item["tag"],
                    "published_at": item.get("published_at"),
                    "supported": int(item.get("supported", 1)),
                    "smoke_test_status": item.get("smoke_test_status", "untested"),
                    "last_checked_at": checked_at,
                    "revoked": int(item.get("revoked", 0)),
                }
                for item in versions
            ],
        )


def retire_missing_tags(config: Config, firmware_id: str, present: set[str]) -> int:
    """Mark this firmware's cached tags that are not in `present` unsupported."""
    with connection(config) as conn:
        rows = conn.execute(
            "SELECT tag FROM firmware_versions WHERE firmware_id = ? AND supported = 1",
            (firmware_id,),
        ).fetchall()
        gone = [row["tag"] for row in rows if row["tag"] not in present]
        conn.executemany(
            "UPDATE firmware_versions SET supported = 0 WHERE firmware_id = ? AND tag = ?",
            [(firmware_id, tag) for tag in gone],
        )
    return len(gone)


def list_firmware_versions(
    config: Config,
    supported_only: bool = True,
    firmware_id: str = "meshtastic",
) -> list[dict[str, Any]]:
    initialize_database(config)
    where = "AND supported = 1" if supported_only else ""
    with connection(config) as conn:
        rows = conn.execute(
            f"""
            SELECT firmware_id, tag, sha, release_name, published_at, supported, smoke_test_status,
                   last_checked_at, revoked
            FROM firmware_versions
            WHERE firmware_id = ? {where}
            ORDER BY rowid ASC
            """,
            (firmware_id,),
        ).fetchall()
    return [row_to_dict(row) for row in rows if row is not None]


def get_firmware_version(
    config: Config,
    tag: str,
    firmware_id: str = "meshtastic",
) -> dict[str, Any] | None:
    initialize_database(config)
    with connection(config) as conn:
        row = conn.execute(
            """
            SELECT firmware_id, tag, sha, release_name, published_at, supported, smoke_test_status,
                   last_checked_at, revoked
            FROM firmware_versions
            WHERE firmware_id = ? AND tag = ?
            """,
            (firmware_id, tag),
        ).fetchone()
    return row_to_dict(row)


def create_build_request(
    config: Config,
    *,
    device_id: str,
    platformio_env: str,
    firmware_tag: str,
    firmware_sha: str,
    prefs_jsonc: str,
    code_options: str | None = None,
    firmware_id: str = "meshtastic",
    firmware_version: str | None = None,
    device_label: str | None = None,
) -> dict[str, Any]:
    initialize_database(config)
    created_at = iso_now()
    token = generate_public_token()
    prefs_hash = hash_prefs(prefs_jsonc)
    with connection(config) as conn:
        conn.execute(
            """
            INSERT INTO build_requests
              (public_token, device_id, device_label, platformio_env, firmware_id, firmware_tag,
               firmware_sha, firmware_version, prefs_jsonc, prefs_hash, code_options, status, created_at)
            VALUES
              (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)
            """,
            (
                token,
                device_id,
                device_label,
                platformio_env,
                firmware_id,
                firmware_tag,
                firmware_sha,
                firmware_version,
                prefs_jsonc,
                prefs_hash,
                code_options,
                created_at,
            ),
        )
        row = conn.execute(
            "SELECT * FROM build_requests WHERE public_token = ?",
            (token,),
        ).fetchone()
    created = row_to_dict(row)
    if created is None:
        raise RuntimeError("No se pudo crear la peticion de compilacion.")
    return created


def get_build_by_token(config: Config, token: str) -> dict[str, Any] | None:
    initialize_database(config)
    with connection(config) as conn:
        row = conn.execute(
            "SELECT * FROM build_requests WHERE public_token = ?",
            (token,),
        ).fetchone()
    return row_to_dict(row)


def decode_code_options(raw: Any) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def owner_names(raw: Any) -> tuple[str | None, str | None]:
    """Node identity for the build page. The rest of userPrefs stays private:
    it carries the WiFi and MQTT passwords."""
    if not raw:
        return None, None
    try:
        prefs = json.loads(raw)
    except (TypeError, ValueError):
        return None, None
    if not isinstance(prefs, dict):
        return None, None
    return (
        prefs.get("USERPREFS_CONFIG_OWNER_LONG_NAME") or None,
        prefs.get("USERPREFS_CONFIG_OWNER_SHORT_NAME") or None,
    )


def public_build_view(row: dict[str, Any]) -> dict[str, Any]:
    long_name, short_name = owner_names(row.get("prefs_jsonc"))
    return {
        "token": row["public_token"],
        "status": row["status"],
        "ownerLongName": long_name,
        "ownerShortName": short_name,
        "deviceId": row["device_id"],
        # Boards can come from a fork's own list, which the static catalogue the
        # build page loads does not have; the label is stored with the build.
        "deviceLabel": row.get("device_label"),
        "platformioEnv": row["platformio_env"],
        "firmwareId": row.get("firmware_id") or "meshtastic",
        "firmwareTag": row["firmware_tag"],
        "firmwareSha": row["firmware_sha"],
        "codeOptions": decode_code_options(row.get("code_options")),
        "attempts": row["attempts"],
        "createdAt": row["created_at"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "expiresAt": row["expires_at"],
        "artifactSha256": row["artifact_sha256"],
        "artifactSizeBytes": row["artifact_size_bytes"],
        "error": row["error_message"] if row["status"] == "failed" else None,
        "errorCode": row.get("error_code") if row["status"] == "failed" else None,
    }


def reset_stale_running(config: Config) -> int:
    cutoff = (utc_now() - timedelta(seconds=config.stale_running_seconds)).isoformat()
    with connection(config) as conn:
        cur = conn.execute(
            """
            UPDATE build_requests
            SET status = 'queued',
                started_at = NULL,
                worker_id = NULL,
                error_message = 'Requeued after stale running timeout.'
            WHERE status = 'running' AND started_at < ?
            """,
            (cutoff,),
        )
        return cur.rowcount


def claim_next_build(config: Config, worker_id: str) -> dict[str, Any] | None:
    initialize_database(config)
    with closing(connect(config)) as conn:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                """
                SELECT * FROM build_requests
                WHERE status = 'queued'
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            conn.execute(
                """
                UPDATE build_requests
                SET status = 'running',
                    attempts = attempts + 1,
                    started_at = ?,
                    worker_id = ?,
                    error_message = NULL
                WHERE id = ?
                """,
                (iso_now(), worker_id, row["id"]),
            )
            claimed = conn.execute("SELECT * FROM build_requests WHERE id = ?", (row["id"],)).fetchone()
            conn.execute("COMMIT")
            return row_to_dict(claimed)
        except Exception:
            conn.execute("ROLLBACK")
            raise


def mark_build_success(
    config: Config,
    build_id: int,
    *,
    artifact_path: Path,
    artifact_sha256: str,
    artifact_size_bytes: int,
    build_log: str,
) -> dict[str, Any]:
    finished = utc_now()
    expires = finished + timedelta(days=config.artifact_ttl_days)
    with connection(config) as conn:
        conn.execute(
            """
            UPDATE build_requests
            SET status = 'succeeded',
                artifact_path = ?,
                artifact_sha256 = ?,
                artifact_size_bytes = ?,
                build_log = ?,
                finished_at = ?,
                expires_at = ?
            WHERE id = ?
            """,
            (
                str(artifact_path),
                artifact_sha256,
                artifact_size_bytes,
                build_log[-20000:],
                finished.isoformat(),
                expires.isoformat(),
                build_id,
            ),
        )
        row = conn.execute("SELECT * FROM build_requests WHERE id = ?", (build_id,)).fetchone()
    updated = row_to_dict(row)
    if updated is None:
        raise RuntimeError("Build not found after success update.")
    return updated


def mark_build_failure(
    config: Config,
    build_id: int,
    *,
    error_message: str,
    build_log: str,
    error_code: str = "unknown",
) -> dict[str, Any]:
    """Record a failure as a translatable code plus one line of evidence.

    error_message is the evidence line, not a paragraph of PlatformIO: the page
    renders the code in the reader's language and shows this underneath.
    """
    with connection(config) as conn:
        conn.execute(
            """
            UPDATE build_requests
            SET status = 'failed',
                error_message = ?,
                error_code = ?,
                build_log = ?,
                finished_at = ?
            WHERE id = ?
            """,
            (error_message[:2000], error_code, build_log[-20000:], iso_now(), build_id),
        )
        row = conn.execute("SELECT * FROM build_requests WHERE id = ?", (build_id,)).fetchone()
    updated = row_to_dict(row)
    if updated is None:
        raise RuntimeError("Build not found after failure update.")
    return updated


def list_expired_successes(config: Config) -> list[dict[str, Any]]:
    cutoff = iso_now()
    with connection(config) as conn:
        rows = conn.execute(
            """
            SELECT * FROM build_requests
            WHERE status = 'succeeded'
              AND expires_at IS NOT NULL
              AND expires_at <= ?
            """,
            (cutoff,),
        ).fetchall()
    return [row_to_dict(row) for row in rows if row is not None]


def build_stats(config: Config) -> dict[str, Any]:
    """Counts for the public health endpoint.

    Deliberately aggregate only: this is served unauthenticated, so it must not
    expose tokens, prefs, device choices or anything else tied to one request.
    """
    with connection(config) as conn:
        counts = {
            str(row["status"]): int(row["total"])
            for row in conn.execute(
                "SELECT status, COUNT(*) AS total FROM build_requests GROUP BY status"
            ).fetchall()
        }
        last_requested = conn.execute(
            "SELECT MAX(created_at) AS last FROM build_requests"
        ).fetchone()["last"]
        # Downloadable right now. Not the same as `succeeded`: expiry is swept
        # periodically and also applied lazily on access, so a build can still be
        # marked succeeded while its window has already closed.
        available = conn.execute(
            """
            SELECT COUNT(*) AS total FROM build_requests
            WHERE status = 'succeeded'
              AND (expires_at IS NULL OR expires_at > ?)
            """,
            (iso_now(),),
        ).fetchone()["total"]
    by_status = {status: counts.get(status, 0) for status in STATUS_ORDER}
    # Every build that produced a firmware, downloadable or not: an expired build
    # succeeded too, its download window just closed. `expired` stays as its own
    # count, so it is a subset of `succeeded` and the statuses no longer add up
    # to `total` (queued + running + succeeded + failed do).
    by_status["succeeded"] += by_status["expired"]
    return {
        "total": sum(counts.values()),
        **by_status,
        "available": int(available),
        "lastRequestedAt": last_requested,
    }


def mark_build_expired(config: Config, build_id: int) -> None:
    with connection(config) as conn:
        conn.execute(
            """
            UPDATE build_requests
            SET status = 'expired'
            WHERE id = ? AND status = 'succeeded'
            """,
            (build_id,),
        )


if __name__ == "__main__":
    cfg = load_config()
    initialize_database(cfg)
    print(f"Initialized database at {cfg.db_path}")
