"""SQLite/PostgreSQL transaction, query, and migration boundary."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastclm.config import settings


SQLITE_MIGRATIONS = settings.root / "migrations" / "sqlite"
POSTGRES_MIGRATIONS = settings.root / "migrations" / "postgres"


def _postgres_query(query: str) -> str:
    translated = query.replace("?", "%s")
    if "INSERT OR IGNORE INTO" in translated.upper():
        translated = translated.replace("INSERT OR IGNORE INTO", "INSERT INTO").rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return translated


class Transaction:
    def __init__(self, connection, dialect: str):
        self.connection = connection
        self.dialect = dialect

    def execute(self, query: str, params: Sequence[Any] = ()):
        return self.connection.execute(_postgres_query(query) if self.dialect == "postgresql" else query, tuple(params))

    def one(self, query: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        row = self.execute(query, params).fetchone()
        return dict(row) if row else None

    def rows(self, query: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self.execute(query, params).fetchall()]

    def scalar(self, query: str, params: Sequence[Any] = ()) -> Any:
        row = self.execute(query, params).fetchone()
        if not row:
            return None
        return next(iter(row.values())) if isinstance(row, dict) else row[0]


class Database:
    def __init__(self, path: str | Path = "", database_url: str = ""):
        self.database_url = database_url.strip()
        self.dialect = "postgresql" if self.database_url.startswith(("postgres://", "postgresql://")) else "sqlite"
        self.path = Path(path or settings.sqlite_path)

    @classmethod
    def from_env(cls) -> "Database":
        return cls(settings.sqlite_path, settings.database_url)

    def connect(self):
        if self.dialect == "postgresql":
            import psycopg
            from psycopg.rows import dict_row

            return psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=10)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[Transaction]:
        connection = self.connect()
        try:
            yield Transaction(connection, self.dialect)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def one(self, query: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self.transaction() as tx:
            return tx.one(query, params)

    def rows(self, query: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self.transaction() as tx:
            return tx.rows(query, params)

    def scalar(self, query: str, params: Sequence[Any] = ()) -> Any:
        with self.transaction() as tx:
            return tx.scalar(query, params)

    def table_names(self) -> list[str]:
        if self.dialect == "postgresql":
            return [row["table_name"] for row in self.rows(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name"
            )]
        return [row["name"] for row in self.rows(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]

    def column_names(self, table: str) -> set[str]:
        if table not in self.table_names():
            raise LookupError("Database table not found")
        if self.dialect == "postgresql":
            return {row["column_name"] for row in self.rows(
                "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=?",
                (table,),
            )}
        return {row["name"] for row in self.rows(f'PRAGMA table_info("{table}")')}

    def _migration_paths(self) -> list[Path]:
        sqlite_paths = {path.stem: path for path in SQLITE_MIGRATIONS.glob("*.sql")}
        if self.dialect == "sqlite":
            return [sqlite_paths[key] for key in sorted(sqlite_paths)]
        postgres_paths = {path.stem: path for path in POSTGRES_MIGRATIONS.glob("*.sql")}
        return [postgres_paths.get(key, sqlite_paths[key]) for key in sorted(sqlite_paths)]

    def migrate(self) -> list[str]:
        connection = self.connect()
        applied: list[str] = []
        try:
            if self.dialect == "postgresql":
                connection.execute("SELECT pg_advisory_lock(hashtext('fastclm_schema_migrations'))")
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
            rows = connection.execute("SELECT version FROM schema_migrations").fetchall()
            done = {row["version"] if isinstance(row, dict) else row[0] for row in rows}
            for path in self._migration_paths():
                if path.stem in done:
                    continue
                script = path.read_text(encoding="utf-8")
                if self.dialect == "sqlite":
                    connection.executescript(script)
                else:
                    script = script.replace(" BLOB ", " BYTEA ")
                    for statement in (part.strip() for part in script.split(";")):
                        if statement:
                            connection.execute(statement)
                timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                query = "INSERT INTO schema_migrations(version,applied_at) VALUES (?,?)"
                connection.execute(_postgres_query(query) if self.dialect == "postgresql" else query, (path.stem, timestamp))
                applied.append(path.stem)
            if self.dialect == "postgresql":
                connection.execute("SELECT pg_advisory_unlock(hashtext('fastclm_schema_migrations'))")
            connection.commit()
            return applied
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


_database: Database | None = None


def get_database() -> Database:
    global _database
    if _database is None:
        _database = Database.from_env()
    return _database


def set_database(database: Database | None) -> None:
    global _database
    _database = database
