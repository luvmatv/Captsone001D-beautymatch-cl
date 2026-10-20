"""src/backup.py with a fake docker: no container, no database."""

import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from src.backup import BackupFailed, backup_database, backup_name, rotate

WHEN = datetime(2026, 10, 20, 9, 16)


class FakeDocker:
    """Answers the four docker commands; `fail` names the step that fails."""

    def __init__(self, fail=None, listing="1; 2 TABLE DATA public products\n2; 3 TABLE DATA public stores\n"):
        self.fail, self.listing, self.commands = fail, listing, []

    def __call__(self, command):
        self.commands.append(list(command))
        what = command[3] if command[1] == "exec" else command[1]
        if what == self.fail:
            return subprocess.CompletedProcess(command, 1, "", f"{what}: something broke\n")
        if what == "cp":
            Path(command[3]).write_bytes(b"PGDMP" + b"x" * 100)
        return subprocess.CompletedProcess(command, 0, self.listing if what == "pg_restore" else "", "")


def test_a_backup_is_dumped_checked_copied_and_the_temporary_file_removed(tmp_path) -> None:
    docker = FakeDocker()
    report = backup_database(52, docker="docker", container="bm-pg", database="beautymatch", directory=tmp_path,
                             runner=docker, now=lambda: WHEN)
    assert report["file"] == str(tmp_path / "beautymatch_daily_20261020_0916_run52.dump")
    assert report["entries"] == 2 and report["bytes"] == 105 and report["deleted"] == []
    assert [c[1:4] for c in docker.commands] == [["exec", "bm-pg", "pg_dump"], ["exec", "bm-pg", "pg_restore"],
                                                ["cp", "bm-pg:/tmp/beautymatch_daily_20261020_0916_run52.dump",
                                                 str(tmp_path / "beautymatch_daily_20261020_0916_run52.partial")],
                                                ["exec", "bm-pg", "rm"]]
    assert docker.commands[0][-1] == "beautymatch" and "-Fc" in docker.commands[0]
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("step", ["pg_dump", "pg_restore", "cp"])
def test_a_failed_step_keeps_nothing_and_says_which(tmp_path, step) -> None:
    docker = FakeDocker(fail=step)
    with pytest.raises(BackupFailed, match="something broke"):
        backup_database(52, docker="docker", container="bm-pg", database="beautymatch", directory=tmp_path,
                        runner=docker, now=lambda: WHEN)
    assert list(tmp_path.iterdir()) == []
    assert docker.commands[-1][3] == "rm"   # the container's temporary file is removed anyway


def test_an_empty_dump_is_not_a_backup(tmp_path) -> None:
    with pytest.raises(BackupFailed, match="no entries"):
        backup_database(52, docker="docker", container="bm-pg", database="beautymatch", directory=tmp_path,
                        runner=FakeDocker(listing=";\n; Archive created\n"), now=lambda: WHEN)
    assert list(tmp_path.iterdir()) == []


def test_rotation_keeps_the_last_14_daily_backups_and_never_the_manual_ones(tmp_path) -> None:
    manual = ["beautymatch_20261016_pre-stable-ids.dump", "beautymatch_20261018_pre-brand-key.dump"]
    for name in manual:
        (tmp_path / name).write_bytes(b"x")
    daily = [backup_name(run, datetime(2026, 10, day, 9, 15)) for run, day in zip(range(40, 60), range(1, 21))]
    for name in daily:
        (tmp_path / name).write_bytes(b"x")
    deleted = rotate(tmp_path, keep=14)
    assert deleted == daily[:6]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(manual + daily[6:])
    assert rotate(tmp_path, keep=14) == []


def test_a_new_backup_rotates_the_oldest(tmp_path) -> None:
    for day in range(1, 15):
        (tmp_path / backup_name(day, datetime(2026, 10, day, 9, 15))).write_bytes(b"x")
    report = backup_database(52, docker="docker", container="bm-pg", database="beautymatch", directory=tmp_path,
                             runner=FakeDocker(), now=lambda: WHEN)
    assert report["deleted"] == ["beautymatch_daily_20261001_0915_run1.dump"]
    assert len(list(tmp_path.glob("beautymatch_daily_*.dump"))) == 14
