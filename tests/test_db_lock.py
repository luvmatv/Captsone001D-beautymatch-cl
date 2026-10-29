"""The database writer lock, between two sessions of beautymatch_test."""

import time

import psycopg
import pytest

from src.db_lock import (
    DatabaseBusy,
    KeepAwake,
    LockLost,
    PooledConnection,
    acquire_writer_lock,
    lock_holder,
    writer_connection,
)

KEEPALIVE_PARAMETERS = {"keepalives": "1", "keepalives_idle": "60", "keepalives_interval": "10",
                        "keepalives_count": "5"}


def has_keepalives(connection: psycopg.Connection) -> bool:
    parameters = connection.info.get_parameters()
    return all(parameters.get(name) == value for name, value in KEEPALIVE_PARAMETERS.items())


@pytest.fixture
def two_sessions(database_url):
    first, second = psycopg.connect(database_url, autocommit=True), psycopg.connect(database_url, autocommit=True)
    try:
        yield first, second
    finally:
        first.close()
        second.close()


def test_one_writer_at_a_time(two_sessions) -> None:
    first, second = two_sessions
    assert lock_holder(second) is None
    acquire_writer_lock(first, r"daily_run C:\BeautyMatch\prod")
    with pytest.raises(DatabaseBusy, match=r"daily_run C:\\BeautyMatch\\prod \(pid \d+"):
        acquire_writer_lock(second, "loader")
    assert lock_holder(second).startswith(r"daily_run C:\BeautyMatch\prod")


def test_the_lock_goes_with_its_session(two_sessions, database_url) -> None:
    first, second = two_sessions
    acquire_writer_lock(first, "daily_run")
    first.close()  # a process that dies: the server releases its lock
    acquire_writer_lock(second, "loader")


def test_the_same_session_does_not_block_itself(two_sessions) -> None:
    first, _ = two_sessions
    lock = acquire_writer_lock(first, "daily_run")
    acquire_writer_lock(first, "daily_run")  # re-entrant within one session
    lock.check()


def test_the_writer_connection_has_tcp_keepalives(database_url) -> None:
    # idle while the scrapers run: keepalives stop Docker or the network dropping it (and the lock)
    with writer_connection(database_url, autocommit=True) as connection:
        assert has_keepalives(connection)
        acquire_writer_lock(connection, "daily_run").check()
    with psycopg.connect(database_url) as plain:
        assert not has_keepalives(plain)


def test_a_pooled_connection_cannot_hold_the_writer_lock(monkeypatch) -> None:
    # Neon's pooler (transaction mode) would drop the session's advisory lock between statements
    connected = []
    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: connected.append(args))
    pooled = "postgresql://bm_owner:s3cret@ep-quiet-sky-123456-pooler.sa-east-1.aws.neon.tech/beautymatch"
    with pytest.raises(PooledConnection, match="the writer lock needs the direct one") as error:
        writer_connection(pooled)
    assert connected == [] and "s3cret" not in str(error.value)


def test_a_remote_writer_connection_asks_for_ssl(monkeypatch) -> None:
    options = {}
    monkeypatch.setattr(psycopg, "connect", lambda url, **kwargs: options.update(kwargs))
    writer_connection("postgresql://bm_owner:s3cret@ep-quiet-sky-123456.sa-east-1.aws.neon.tech/beautymatch")
    assert options["sslmode"] == "require" and options["keepalives"] == 1


def test_a_lost_lock_or_connection_is_detected(two_sessions) -> None:
    first, second = two_sessions
    lock = acquire_writer_lock(first, "daily_run")
    lock.check()
    first.execute("SELECT pg_advisory_unlock_all()")
    with pytest.raises(LockLost, match="no longer holds"):
        lock.check()
    lock = acquire_writer_lock(second, "loader")
    second.close()
    with pytest.raises(LockLost, match="was lost"):
        lock.check()


def test_keep_awake_sends_select_1_until_the_block_ends(database_url) -> None:
    with writer_connection(database_url, autocommit=True) as connection:
        lock = acquire_writer_lock(connection, "daily_run")
        with KeepAwake(connection, interval=0.02) as awake:
            time.sleep(0.2)
        pings = awake.pings
        time.sleep(0.1)
        assert pings >= 3 and awake.pings == pings and awake.error is None   # stopped with the block
        lock.check()   # the lock is still held


def test_keep_awake_records_a_lost_connection_without_raising(two_sessions) -> None:
    # as Neon closing a suspended compute's connections: the first failed SELECT 1 ends the pings
    first, second = two_sessions
    lock = acquire_writer_lock(first, "daily_run")
    with KeepAwake(first, interval=0.02) as awake:
        second.execute("SELECT pg_terminate_backend(%s)", (first.info.backend_pid,))
        deadline = time.monotonic() + 5
        while awake.error is None and time.monotonic() < deadline:
            time.sleep(0.02)
    assert isinstance(awake.error, psycopg.OperationalError)
    with pytest.raises(LockLost, match="was lost"):
        lock.check()
