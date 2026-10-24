"""What the deployed API (Azure Container Apps + Neon) relies on, without a database or a container."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import db
from src.api.config import Settings
from src.api.main import create_app
from src.api.semantic import QueryEmbedder

ROOT = Path(__file__).resolve().parents[2]
NEON_POOLED = ("postgresql://bm_api:s3cret@ep-quiet-sky-123456-pooler.sa-east-1.aws.neon.tech/beautymatch"
               "?sslmode=require")


def test_database_url_wins_over_the_pg_variables() -> None:
    settings = Settings.from_env({"DATABASE_URL": NEON_POOLED, "PGHOST": "localhost", "API_POOL_MAX_SIZE": "4"})
    assert settings.conninfo() == NEON_POOLED  # used as given: Neon's URL carries sslmode=require
    assert (settings.host, settings.database, settings.pool_max_size) == (
        "ep-quiet-sky-123456-pooler.sa-east-1.aws.neon.tech", "beautymatch", 4)
    assert settings.pooled
    assert "s3cret" not in repr(settings)


def test_without_database_url_the_pg_variables_are_required() -> None:
    with pytest.raises(RuntimeError, match="or set DATABASE_URL"):
        Settings.from_env({"PGHOST": "localhost"})
    local = Settings.from_env({"PGHOST": "localhost", "PGUSER": "postgres", "PGPASSWORD": "dev",
                               "PGDATABASE": "beautymatch"})
    assert local.url is None and not local.pooled and "password=dev" in local.conninfo()


def pool_of(settings, monkeypatch):
    made = {}

    class FakePool:
        check_connection = staticmethod(lambda connection: None)

        def __init__(self, conninfo, **kwargs):
            made.update(kwargs, conninfo=conninfo)

    monkeypatch.setattr(db, "ConnectionPool", FakePool)
    db.create_pool(settings)
    return made


def test_the_pool_lets_neon_sleep_and_skips_prepared_statements_on_its_pooler(monkeypatch) -> None:
    neon = pool_of(Settings.from_env({"DATABASE_URL": NEON_POOLED}), monkeypatch)
    # no connection held while nobody asks: Neon's free compute hours are not spent idle
    assert neon["min_size"] == 0 and neon["max_idle"] == db.REMOTE_MAX_IDLE_SECONDS
    # PgBouncer in transaction mode does not keep prepared statements
    assert neon["kwargs"]["prepare_threshold"] is None and neon["open"] is False
    local = pool_of(Settings.from_env({"PGHOST": "localhost", "PGUSER": "postgres", "PGPASSWORD": "dev",
                                       "PGDATABASE": "beautymatch"}), monkeypatch)
    assert local["min_size"] == 1 and "prepare_threshold" not in local["kwargs"]


def test_healthz_never_touches_the_database_and_says_where_the_model_is() -> None:
    app = create_app(use_database=False)  # no pool at all: a probe must not need one
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok", "semantic_model": "not_loaded"}
        app.state.embedder._model = object()
        assert client.get("/healthz").json()["semantic_model"] == "ready"
    assert "/healthz" not in app.openapi()["paths"]  # not part of the documented API


def test_the_model_state_while_it_loads() -> None:
    embedder = QueryEmbedder(loader=object)
    with embedder._lock:
        assert embedder.state == "loading"
    assert embedder.state == "not_loaded"


def test_the_image_build_context_has_no_secrets_or_data() -> None:
    # allowlist: everything is ignored except the code and the API's requirements
    lines = [line.strip() for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    assert lines[0] == "*" and set(lines[1:3]) == {"!src/", "!requirements-api.txt"}
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "HF_HUB_OFFLINE=1" in dockerfile and "download.pytorch.org/whl/cpu" in dockerfile
    assert "USER app" in dockerfile
