"""The database writer lock, between two sessions of beautymatch_test."""

import psycopg
import pytest

from src.db_lock import DatabaseBusy, LockLost, acquire_writer_lock, lock_holder


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
