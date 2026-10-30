"""One writer at a time on the database, whatever copy of the repository it runs from.

The daily run, the loader and the pipeline, run from their entry points (the
daily run, `python -m src.loader.raw_listings`, `python -m src.matching.pipeline`),
take a PostgreSQL session advisory lock before writing. The file lock of the
daily run (RunLock) only stops a second run of the same copy; this one stops
two copies (the OneDrive working tree and C:\\BeautyMatch\\prod) writing at once.

- Session level: held by the connection, released when it closes or its
  process dies; a rollback does not release it.
- Scoped to the database: beautymatch_test (the tests) and beautymatch do
  not share it.
- Fails closed and does not wait: if another session holds it, DatabaseBusy
  says who (its application_name, pid and since when).
- WriterLock.check() before each writing step: if the connection was lost or
  the lock is no longer held, LockLost; the step must not write.

Library functions (load_file, run_matching, write_plan...) never take it:
they run inside an entry point that holds it, on its connection.

The entry points open that connection with writer_connection(): TCP
keepalives, so the connection survives sitting idle while the scrapers run
(15-20 minutes) instead of being dropped by Docker's port forwarding or the
network, which would release the lock.

TCP keepalives are not queries: Neon (free plan) suspends a compute after 5
minutes without one and closes its connections (run 60, 2026-10-28: the lock
was lost while the scrapers ran). KeepAwake sends SELECT 1 on the lock's
connection every minute meanwhile.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

import psycopg

from src.db_config import connection_options, describe, is_pooled

# A fixed 64-bit key ("BMWRITER" in ASCII). pg_locks shows a bigint advisory key
# as classid (high 32 bits) and objid (low 32 bits), with objsubid 1.
WRITER_LOCK_KEY = int.from_bytes(b"BMWRITER", "big", signed=True)
_CLASSID, _OBJID = (WRITER_LOCK_KEY >> 32) & 0xFFFFFFFF, WRITER_LOCK_KEY & 0xFFFFFFFF

HOLDER = """
SELECT a.application_name, a.pid, a.backend_start, a.state
FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
WHERE l.locktype = 'advisory' AND l.classid = %s AND l.objid = %s AND l.objsubid = 1 AND l.granted
  AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())
"""
HELD_BY_ME = HOLDER + " AND l.pid = pg_backend_pid()"

# libpq TCP keepalives: a probe after 60 s idle, then every 10 s; the connection
# is declared dead after 5 unanswered probes (about 2 minutes).
KEEPALIVES = {"keepalives": 1, "keepalives_idle": 60, "keepalives_interval": 10, "keepalives_count": 5}


class PooledConnection(ValueError):
    """A pooled connection string where the writer lock needs a session of its own."""


def writer_connection(database_url: str, **kwargs) -> psycopg.Connection:
    """A connection for an entry point that will hold the writer lock (with TCP keepalives).

    A remote database gets SSL unless the URL says otherwise. Neon's pooled
    connection string is refused before connecting: its pooler (transaction
    mode) does not keep the session's advisory lock (src/db_config.py).
    """
    if is_pooled(database_url):
        raise PooledConnection(f"{describe(database_url)} is a pooled connection: the writer lock needs the "
                               "direct one (the same URL without '-pooler' in the host)")
    return psycopg.connect(database_url, **KEEPALIVES, **connection_options(database_url), **kwargs)


class DatabaseBusy(RuntimeError):
    """Another session holds the writer lock."""


class LockLost(RuntimeError):
    """The connection holding the writer lock was lost, or no longer holds it."""


def lock_holder(connection: psycopg.Connection) -> str | None:
    """Who holds the writer lock, as a readable line; None if nobody."""
    row = connection.execute(HOLDER, (_CLASSID, _OBJID)).fetchone()
    if row is None:
        return None
    name, pid, since, state = row
    return f"{name or '(no application_name)'} (pid {pid}, connected since {since:%Y-%m-%d %H:%M}, {state})"


@dataclass
class WriterLock:
    connection: psycopg.Connection
    name: str

    def check(self) -> None:
        """Raise LockLost unless this connection is alive and still holds the lock."""
        try:
            held = self.connection.execute(HELD_BY_ME, (_CLASSID, _OBJID)).fetchone()
        except psycopg.Error as error:
            raise LockLost(f"{self.name}: the database connection holding the writer lock was lost ({error})") from error
        if held is None:
            raise LockLost(f"{self.name}: this session no longer holds the database writer lock")


KEEP_AWAKE_SECONDS = 60  # well under Neon's 5 minutes without a query


class KeepAwake:
    """SELECT 1 on a connection every `interval` seconds, in a thread, while the block runs.

    For the minutes the scrapers run and the writer lock's connection has nothing
    to do. Nothing else may use the connection meanwhile. The first failure ends
    the pings and stays in `error` (no exception here): the caller then treats
    the lock as lost and writes nothing.
    """

    def __init__(self, connection: psycopg.Connection, interval: float = KEEP_AWAKE_SECONDS,
                 ping: Callable[[psycopg.Connection], object] | None = None) -> None:
        self.connection = connection
        self.interval = interval
        self.ping = ping or (lambda c: c.execute("SELECT 1"))
        self.pings = 0
        self.error: Exception | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="keep-db-awake", daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.ping(self.connection)
            except psycopg.Error as error:
                self.error = error
                return
            self.pings += 1

    def __enter__(self) -> KeepAwake:
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._stop.set()
        self._thread.join()


def acquire_writer_lock(connection: psycopg.Connection, name: str) -> WriterLock:
    """Take the writer lock on this connection's session, or raise DatabaseBusy (no wait).

    name identifies the writer in the holder message (application_name), e.g.
    "daily_run C:\\BeautyMatch\\prod".
    """
    connection.execute("SELECT set_config('application_name', %s, false)", (name[:63],))
    if not connection.execute("SELECT pg_try_advisory_lock(%s)", (WRITER_LOCK_KEY,)).fetchone()[0]:
        holder = lock_holder(connection) or "a session that has just released it"
        if not connection.autocommit:
            connection.rollback()
        raise DatabaseBusy(f"another process is writing to the database: {holder}")
    return WriterLock(connection, name)
