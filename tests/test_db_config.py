"""src/db_config.py: the .env file and telling the local database from a managed one (no database needed)."""

import pytest

from src.db_config import connection_options, describe, is_local, is_pooled, load_env_file

NEON = "postgresql://bm_owner:s3cret@ep-quiet-sky-123456.sa-east-1.aws.neon.tech/beautymatch?sslmode=require"
NEON_POOLED = "postgresql://bm_owner:s3cret@ep-quiet-sky-123456-pooler.sa-east-1.aws.neon.tech/beautymatch"


def test_the_env_file_fills_what_the_environment_does_not_set(tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text("\ufeff# prod settings\nDATABASE_URL=\"" + NEON + "\"\n\nexport BM_BACKUP_DIR='D:\\backups'\n"
                   "API_POOL_MAX_SIZE=4\nnot a setting\n", encoding="utf-8")
    environ = {"API_POOL_MAX_SIZE": "10"}
    assert load_env_file(env, environ) == ["DATABASE_URL", "BM_BACKUP_DIR"]
    assert environ == {"API_POOL_MAX_SIZE": "10", "DATABASE_URL": NEON, "BM_BACKUP_DIR": "D:\\backups"}


def test_no_env_file_changes_nothing(tmp_path) -> None:
    environ = {}
    assert load_env_file(tmp_path / ".env", environ) == [] and environ == {}


@pytest.mark.parametrize(("url", "local"), [
    ("postgresql://postgres:dev@localhost:5432/beautymatch", True),
    ("postgresql://postgres:dev@127.0.0.1/beautymatch", True),
    ("host=/var/run/postgresql dbname=beautymatch", True),
    ("dbname=beautymatch", True),
    (NEON, False),
    (NEON_POOLED, False),
])
def test_local_or_managed(url, local) -> None:
    assert is_local(url) is local


def test_the_pooled_neon_url_is_recognized() -> None:
    assert is_pooled(NEON_POOLED) and not is_pooled(NEON)
    assert not is_pooled("postgresql://postgres:dev@localhost/beautymatch")


def test_logs_never_show_the_password() -> None:
    assert describe(NEON) == "ep-quiet-sky-123456.sa-east-1.aws.neon.tech/beautymatch"
    assert "s3cret" not in describe(NEON_POOLED)


def test_a_remote_database_gets_ssl_unless_the_url_says_otherwise() -> None:
    assert connection_options(NEON_POOLED) == {"sslmode": "require"}
    assert connection_options(NEON) == {}                      # the URL already asks for it
    assert connection_options("postgresql://postgres:dev@localhost/beautymatch") == {}
