"""Where the database is: the local Docker container or a managed one (Neon).

The writer entry points (daily run, loader, pipeline, embeddings) take the
database from DATABASE_URL, or the local default. load_env_file() reads it,
and any other setting, from a .env file in the working directory, so the
scheduled task in C:\\BeautyMatch\\prod uses prod's .env without setting
Windows environment variables. A variable already set in the environment
wins over the file. .env is in .gitignore: the URL carries the password.

A remote database:
- is not waited for by starting Docker (the container is only the local one);
- is reached with SSL (sslmode=require unless the URL says otherwise);
- must be the direct connection. Neon's pooled one (a host with "-pooler")
  is PgBouncer in transaction mode: it does not keep a session's advisory
  lock, so the writer lock (src/db_lock.py) would be released between
  statements without anyone noticing. writer_connection refuses it.
"""

from __future__ import annotations

import os
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict

LOCAL_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1"})


def load_env_file(path: Path = Path(".env"), environ: dict | None = None) -> list[str]:
    """Set the KEY=VALUE lines of path that are not already in the environment. Returns the keys set."""
    environ = os.environ if environ is None else environ
    if not path.is_file():
        return []
    added = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.removeprefix("export ").split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in environ:
            environ[key] = value
            added.append(key)
    return added


def _params(database_url: str) -> dict:
    return conninfo_to_dict(database_url)


def is_local(database_url: str) -> bool:
    """The local Docker database (localhost, or a Unix socket), as opposed to a managed one."""
    host = str(_params(database_url).get("host") or "")
    return host in LOCAL_HOSTS or host.startswith("/")


def is_pooled(database_url: str) -> bool:
    """Neon's pooled connection string: its host has "-pooler" (PgBouncer, transaction mode)."""
    return "-pooler" in str(_params(database_url).get("host") or "")


def describe(database_url: str) -> str:
    """host/dbname, for logs: never the password."""
    params = _params(database_url)
    return f"{params.get('host') or 'localhost'}/{params.get('dbname') or ''}"


def connection_options(database_url: str) -> dict:
    """Extra libpq options for a remote database: SSL required unless the URL sets sslmode."""
    if is_local(database_url) or "sslmode" in _params(database_url):
        return {}
    return {"sslmode": "require"}
