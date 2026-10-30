"""Daily backup of the database, after each run (src/daily_run.py), keeping the last KEEP.

    pg_dump -Fc inside the database container -> checked with pg_restore --list
    -> copied to BACKUP_DIRECTORY as beautymatch_daily_<local date>_<time>_run<N>.dump

The container's pg_dump (PostgreSQL 17) dumps the local database by name, or a
managed one (Neon) by its URL: the container is then only the client. A managed
database must not run a newer major version than that client (pg_dump refuses).
Neon's free plan keeps 6 hours of history, so these files are the real backups.

Only files named beautymatch_daily_*.dump are rotated: backups made by hand
before a change (beautymatch_<date>_pre-*.dump) are never deleted here.
BACKUP_DIRECTORY is BM_BACKUP_DIR, by default ~/bm-backups.

Restore one into a scratch database first, never straight over the live one:
    docker cp <file> bm-pg:/tmp/restore.dump
    docker exec bm-pg createdb -U postgres beautymatch_restore
    docker exec bm-pg pg_restore -U postgres -d beautymatch_restore --no-owner /tmp/restore.dump
"""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from src.db_config import connection_options

logger = logging.getLogger(__name__)

BACKUP_DIRECTORY = Path(os.environ.get("BM_BACKUP_DIR", Path.home() / "bm-backups"))
KEEP = 14
PREFIX = "beautymatch_daily_"
DUMP_TIMEOUT_SECONDS = 300   # ~20 MB today: a few seconds
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


class BackupFailed(RuntimeError):
    pass


def _run(command: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(command), capture_output=True, text=True, timeout=DUMP_TIMEOUT_SECONDS,
                          creationflags=NO_WINDOW)


def backup_name(run_id: int, when: datetime) -> str:
    return f"{PREFIX}{when:%Y%m%d_%H%M}_run{run_id}.dump"


def rotate(directory: Path, keep: int = KEEP) -> list[str]:
    """Delete the oldest daily backups beyond `keep` (by name: the name starts with the date). Returns their names."""
    daily = sorted(directory.glob(f"{PREFIX}*.dump"))
    old = daily[:-keep] if keep > 0 else daily
    for path in old:
        path.unlink()
    return [path.name for path in old]


def dump_command(container: str, inside: str, database: str) -> list[str]:
    """pg_dump inside the container: a local database by name (as user postgres), a remote one by URL (with SSL)."""
    if "://" not in database:
        return ["exec", container, "pg_dump", "-U", "postgres", "-Fc", "-f", inside, database]
    options = connection_options(database)
    url = database + (("&" if "?" in database else "?") + "sslmode=" + options["sslmode"] if options else "")
    return ["exec", container, "pg_dump", "-Fc", "-f", inside, f"--dbname={url}"]


def backup_database(run_id: int, *, docker: str, container: str, database: str,
                    directory: Path = BACKUP_DIRECTORY, keep: int = KEEP, runner: Runner = _run,
                    now: Callable[[], datetime] = lambda: datetime.now().astimezone()) -> dict:
    """Dump, check, copy and rotate. Raises BackupFailed with what went wrong; nothing half-written is kept.

    database: the local database's name, or a remote database's URL (never logged: it has the password).
    """
    name = backup_name(run_id, now())
    inside = f"/tmp/{name}"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    partial = target.with_suffix(".partial")

    def step(what: str, command: Sequence[str]) -> subprocess.CompletedProcess:
        result = runner(command)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            raise BackupFailed(f"{what}: {detail[-1] if detail else f'exit {result.returncode}'}")
        return result

    try:
        step("pg_dump", [docker, *dump_command(container, inside, database)])
        listing = step("pg_restore --list", [docker, "exec", container, "pg_restore", "--list", inside]).stdout
        entries = sum(1 for line in listing.splitlines() if line.strip() and not line.startswith(";"))
        if entries == 0:
            raise BackupFailed("pg_restore --list: the dump has no entries")
        step("docker cp", [docker, "cp", f"{container}:{inside}", str(partial)])
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        runner([docker, "exec", container, "rm", "-f", inside])  # best effort: the container's /tmp
    deleted = rotate(directory, keep)
    size = target.stat().st_size
    logger.info("backup: %s (%.1f MB, %d entries); kept the last %d, deleted %s",
                name, size / 1e6, entries, keep, deleted or "none")
    return {"file": str(target), "bytes": size, "entries": entries, "deleted": deleted}
