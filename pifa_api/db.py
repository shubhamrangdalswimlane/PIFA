"""PostgreSQL access: one short-lived connection per request (serverless-friendly, no pool)."""

import logging
from collections.abc import Iterator
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .config import get_settings

log = logging.getLogger(__name__)
MIGRATIONS = Path(__file__).with_name("migrations")
_migrated = False


def connect() -> psycopg.Connection:
    s = get_settings()
    return psycopg.connect(
        s.database_url,
        row_factory=dict_row,
        options=f"-c search_path={s.db_schema}",
        connect_timeout=10,
    )


def get_db() -> Iterator[psycopg.Connection]:
    """FastAPI dependency: commit on success, roll back on any error."""
    ensure_migrated()
    with connect() as conn:  # psycopg commits on clean exit, rolls back on exception
        yield conn


def ensure_migrated() -> None:
    global _migrated
    if _migrated or not get_settings().auto_migrate:
        return
    migrate()
    _migrated = True


def migrate() -> list[str]:
    """Apply pending SQL migrations once, guarded by an advisory lock for concurrent cold starts."""
    schema = get_settings().db_schema
    applied: list[str] = []
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(4242001)")
        conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in done:
                continue
            log.info("applying migration %s", path.name)
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
    return applied


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("applied:", migrate() or "nothing (up to date)")
