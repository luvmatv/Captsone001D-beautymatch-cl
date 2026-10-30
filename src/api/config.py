"""API settings: the database from DATABASE_URL or the standard PostgreSQL
environment variables, CORS origins from API_CORS_ORIGINS.

DATABASE_URL wins when set: the deployed API (Azure Container Apps) gets
Neon's pooled connection string from a secret. The API only reads, so the
pooler is fine here (the daily run's writer lock needs the direct one). Neon's
URLs carry sslmode=require; the URL is used as given.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from psycopg.conninfo import conninfo_to_dict, make_conninfo

REQUIRED = ("PGHOST", "PGUSER", "PGPASSWORD", "PGDATABASE")


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    user: str
    password: str
    database: str
    pool_max_size: int = 10
    url: str | None = None  # DATABASE_URL, used as the connection string when set

    def __repr__(self) -> str:  # never print the password in logs or tracebacks
        return f"Settings(host={self.host!r}, port={self.port}, user={self.user!r}, database={self.database!r})"

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        pool_max_size = int(env.get("API_POOL_MAX_SIZE") or 10)
        url = (env.get("DATABASE_URL") or "").strip()
        if url:
            params = conninfo_to_dict(url)
            return cls(host=str(params.get("host") or "localhost"), port=int(params.get("port") or 5432),
                       user=str(params.get("user") or ""), password="", database=str(params.get("dbname") or ""),
                       pool_max_size=pool_max_size, url=url)
        missing = [name for name in REQUIRED if not env.get(name)]
        if missing:
            raise RuntimeError(f"Missing environment variables: {', '.join(missing)} "
                               "(or set DATABASE_URL; see .env.example)")
        return cls(
            host=env["PGHOST"],
            port=int(env.get("PGPORT") or 5432),
            user=env["PGUSER"],
            password=env["PGPASSWORD"],
            database=env["PGDATABASE"],
            pool_max_size=pool_max_size,
        )

    @property
    def pooled(self) -> bool:
        """Neon's pooled connection string: PgBouncer in transaction mode."""
        return "-pooler" in self.host

    def conninfo(self) -> str:
        if self.url:
            return self.url
        return make_conninfo(
            host=self.host, port=self.port, user=self.user, password=self.password, dbname=self.database
        )


def cors_origins_from_env(env: Mapping[str, str] = os.environ) -> list[str]:
    """Browser origins allowed to call the API, from API_CORS_ORIGINS (comma-separated).

    Unset or empty means no cross-origin access. An origin is scheme + host +
    port, exactly as the browser sends it ("http://localhost:5173", no path);
    a trailing slash is dropped because browsers never send one.
    """
    origins = [origin.strip().rstrip("/") for origin in (env.get("API_CORS_ORIGINS") or "").split(",")]
    origins = [origin for origin in origins if origin]
    invalid = [origin for origin in origins if origin != "*" and not origin.startswith(("http://", "https://"))]
    if invalid:
        raise RuntimeError(f"API_CORS_ORIGINS entries must start with http:// or https://: {', '.join(invalid)}")
    return origins
