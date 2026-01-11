from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from subflow.config import Settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply SubFlow SQL migrations to PostgreSQL.")
    parser.add_argument(
        "--migrations-dir",
        default="infra/migrations",
        help="Directory containing *.sql migrations (default: infra/migrations)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override database url (otherwise uses subflow Settings.database_url)",
    )
    return parser.parse_args()


def _ensure_migrations_table(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          name TEXT PRIMARY KEY,
          applied_at TIMESTAMPTZ NOT NULL
        )
        """,
    )


def _applied(conn: psycopg.Connection) -> set[str]:
    _ensure_migrations_table(conn)
    rows = conn.execute("SELECT name FROM schema_migrations").fetchall()
    return {str(r[0]) for r in rows}


def _apply_one(conn: psycopg.Connection, name: str, sql: str) -> None:
    conn.execute(sql)
    conn.execute(
        "INSERT INTO schema_migrations (name, applied_at) VALUES (%s, %s)",
        (name, datetime.now(tz=timezone.utc)),
    )


def main() -> None:
    args = _parse_args()
    settings = Settings()
    migrations_dir = Path(args.migrations_dir).resolve()
    if not migrations_dir.exists():
        raise SystemExit(f"migrations dir not found: {migrations_dir}")

    database_url = args.database_url or os.environ.get("DATABASE_URL") or settings.database_url
    sql_files = sorted(p for p in migrations_dir.glob("*.sql") if p.is_file())
    if not sql_files:
        raise SystemExit(f"no .sql migrations found in {migrations_dir}")

    with psycopg.connect(database_url, autocommit=False) as conn:
        already = _applied(conn)
        for path in sql_files:
            name = path.name
            if name in already:
                continue
            sql = path.read_text(encoding="utf-8")
            _apply_one(conn, name, sql)
            conn.commit()
            print(f"applied {name}")


if __name__ == "__main__":
    main()

