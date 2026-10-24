"""PostgreSQL test environment.

Order of preference:
1. ``SQLNINJA_PG_DSN`` (admin DSN; used by CI with a ``postgres`` service container);
2. an embedded server from the optional ``pgserver`` package (local development);
3. otherwise PostgreSQL tests are skipped.

A fresh database ``sqlninja_test`` is created with the synthetic fixture data, plus a
``sqlninja_reader`` role that can only SELECT, mirroring the least-privilege deployment the
docs recommend.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from psycopg import conninfo as ci

from sqlguard_ninja import Policy
from sqlguard_ninja.benchmarking.fixtures import populate

ROOT = Path(__file__).resolve().parents[1]
DB = "sqlninja_test"
READER = "sqlninja_reader"


@dataclass(frozen=True)
class PgEnv:
    admin_dsn: str
    reader_dsn: str


def _admin_dsn() -> str | None:
    dsn = os.environ.get("SQLNINJA_PG_DSN")
    if dsn:
        return dsn
    try:
        import pgserver
    except ImportError:
        return None
    server = pgserver.get_server(str(ROOT / ".pgdata"), cleanup_mode="stop")
    return str(server.get_uri())


def setup_pg(policy: Policy) -> PgEnv | None:
    import psycopg

    admin = _admin_dsn()
    if admin is None:
        return None
    password = secrets.token_hex(16)  # throwaway test credential, never persisted
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {DB}")
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (READER,)).fetchone()
        verb = "ALTER" if exists else "CREATE"
        conn.execute(
            psycopg.sql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(
                psycopg.sql.SQL(verb), psycopg.sql.Identifier(READER), psycopg.sql.Literal(password)
            )
        )
    db_admin = ci.make_conninfo(admin, dbname=DB)
    with psycopg.connect(db_admin) as conn:
        populate(conn, policy, "postgres")
        conn.execute(f"GRANT CONNECT ON DATABASE {DB} TO {READER}")
        conn.execute(f"GRANT USAGE ON SCHEMA public TO {READER}")
        conn.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {READER}")
        conn.execute("ANALYZE")
        conn.commit()
    reader = ci.make_conninfo(db_admin, user=READER, password=password)
    return PgEnv(admin_dsn=db_admin, reader_dsn=reader)
