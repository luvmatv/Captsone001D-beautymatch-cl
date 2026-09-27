"""API settings, read from the standard PostgreSQL environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from psycopg.conninfo import make_conninfo

REQUIRED = ("PGHOST", "PGUSER", "PGPASSWORD", "PGDATABASE")


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    user: str
    password: str
    database: str
    pool_max_size: int = 10

    def __repr__(self) -> str:  # never print the password in logs or tracebacks
        return f"Settings(host={self.host!r}, port={self.port}, user={self.user!r}, database={self.database!r})"

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        missing = [name for name in REQUIRED if not env.get(name)]
        if missing:
            raise RuntimeError(f"Missing environment variables: {', '.join(missing)} (see .env.example)")
        return cls(
            host=env["PGHOST"],
            port=int(env.get("PGPORT") or 5432),
            user=env["PGUSER"],
            password=env["PGPASSWORD"],
            database=env["PGDATABASE"],
            pool_max_size=int(env.get("API_POOL_MAX_SIZE") or 10),
        )

    def conninfo(self) -> str:
        return make_conninfo(
            host=self.host, port=self.port, user=self.user, password=self.password, dbname=self.database
        )
