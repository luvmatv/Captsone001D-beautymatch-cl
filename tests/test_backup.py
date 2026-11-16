"""src/backup.py with a fake docker: no container, no database."""

import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from src.backup import BackupFailed, backup_database, backup_name, dump_command, rotate, tables_file

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


def test_a_managed_database_is_dumped_by_url_with_ssl(tmp_path) -> None:
    # the container is only pg_dump's client: it connects to Neon, not to its own server
    docker = FakeDocker()
    url = "postgresql://bm_owner:s3cret@ep-quiet-sky-123456.sa-east-1.aws.neon.tech/beautymatch"
    backup_database(56, docker="docker", container="bm-pg", database=url, directory=tmp_path, runner=docker,
                    now=lambda: WHEN)
    dump = docker.commands[0]
    assert dump[1:4] == ["exec", "bm-pg", "pg_dump"] and "-U" not in dump and "-Fc" in dump
    assert dump[-1] == f"--dbname={url}?sslmode=require"
    assert dump_command("bm-pg", "/tmp/x", url + "?sslmode=verify-full")[-1] == f"--dbname={url}?sslmode=verify-full"


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


def fake_tables(path: Path) -> dict:
    path.write_bytes(b"PK zip")
    return {"format": 1, "tables": {"raw_listings": {"columns": ["raw_listing_id"], "rows": 3},
                                    "fragrances": {"columns": ["fragrance_id"], "rows": 2}}}


def test_without_embeddings_the_dump_skips_two_tables_data_and_a_zip_has_them(tmp_path) -> None:
    docker = FakeDocker()
    report = backup_database(52, docker="docker", container="bm-pg", database="beautymatch", directory=tmp_path,
                             runner=docker, now=lambda: WHEN, tables=fake_tables)
    dump = docker.commands[0]
    assert "--exclude-table-data=public.raw_listings" in dump and "--exclude-table-data=public.fragrances" in dump
    assert dump[-1] == "beautymatch"
    name = "beautymatch_daily_20261020_0916_run52"
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{name}.dump", f"{name}.tables.zip"]
    assert report["tables_file"] == str(tmp_path / f"{name}.tables.zip") and report["bytes"] == 105 + 6
    assert report["table_rows"] == {"raw_listings": 3, "fragrances": 2}


@pytest.mark.parametrize("step", ["cp", "tables"])
def test_a_failed_export_keeps_neither_file(tmp_path, step) -> None:
    def broken_tables(path):
        path.write_bytes(b"half")
        raise RuntimeError("connection lost")
    with pytest.raises(BackupFailed, match="something broke" if step == "cp" else "export tables: connection lost"):
        backup_database(52, docker="docker", container="bm-pg", database="beautymatch", directory=tmp_path,
                        runner=FakeDocker(fail=step), now=lambda: WHEN,
                        tables=broken_tables if step == "tables" else fake_tables)
    assert list(tmp_path.iterdir()) == []


def test_rotation_also_deletes_the_tables_zip(tmp_path) -> None:
    for day in range(1, 16):
        dump = tmp_path / backup_name(day, datetime(2026, 10, day, 9, 15))
        dump.write_bytes(b"x")
        if day > 1:
            tables_file(dump).write_bytes(b"z")
    deleted = rotate(tmp_path, keep=14)
    assert deleted == ["beautymatch_daily_20261001_0915_run1.dump"]   # a complete dump, without a zip: fine
    deleted = rotate(tmp_path, keep=13)
    assert deleted == ["beautymatch_daily_20261002_0915_run2.dump"]
    assert not (tmp_path / "beautymatch_daily_20261002_0915_run2.tables.zip").exists()
    assert len(list(tmp_path.glob("*.tables.zip"))) == 13


def test_a_new_backup_rotates_the_oldest(tmp_path) -> None:
    for day in range(1, 15):
        (tmp_path / backup_name(day, datetime(2026, 10, day, 9, 15))).write_bytes(b"x")
    report = backup_database(52, docker="docker", container="bm-pg", database="beautymatch", directory=tmp_path,
                             runner=FakeDocker(), now=lambda: WHEN)
    assert report["deleted"] == ["beautymatch_daily_20261001_0915_run1.dump"]
    assert len(list(tmp_path.glob("beautymatch_daily_*.dump"))) == 14
