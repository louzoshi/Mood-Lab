"""DuckDB connection and migrations.

Migrations are the numbered `migrations/NNN_name.sql` files, applied in order, each once;
applied versions are recorded in `schema_migrations`.
"""

from pathlib import Path

import duckdb

from .config import Settings

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def connect(path: str | None = None) -> duckdb.DuckDBPyConnection:
    """Open the database and bring its schema up to date."""
    path = path or Settings.from_env().db_path
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(path)
    # GLOBAL so cursor() connections inherit it: TIMESTAMPTZ values come back in UTC.
    con.execute("SET GLOBAL TimeZone = 'UTC'")
    migrate(con)
    return con


def migrate(con: duckdb.DuckDBPyConnection) -> list[int]:
    """Apply pending migrations; returns the versions applied."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       VARCHAR NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
        )
    """)
    done = {v for (v,) in con.execute("SELECT version FROM schema_migrations").fetchall()}
    applied = []
    for file in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(file.name[:3])
        if version in done:
            continue
        con.execute("BEGIN")
        try:
            con.execute(file.read_text())
            con.execute("INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                        [version, file.stem])
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        applied.append(version)
    return applied
