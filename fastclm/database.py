"""Small SQLite transaction and migration boundary."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastclm.config import settings


MIGRATIONS = settings.root / "migrations" / "sqlite"


class Transaction:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def execute(self, query: str, params: Sequence[Any] = ()):
        return self.connection.execute(query, tuple(params))

    def one(self, query: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        row = self.execute(query, params).fetchone()
        return dict(row) if row else None

    def rows(self, query: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self.execute(query, params).fetchall()]

    def scalar(self, query: str, params: Sequence[Any] = ()) -> Any:
        row = self.execute(query, params).fetchone()
        return row[0] if row else None


class Database:
    def __init__(self, path: str | Path = ""):
        self.path = Path(path or settings.sqlite_path)
        self.dialect = "sqlite"

    @classmethod
    def from_env(cls) -> "Database":
        return cls(settings.sqlite_path)

    def connect(self) -> sqlite3.Connection:
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
            yield Transaction(connection)
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

    def migrate(self) -> list[str]:
        connection = self.connect()
        applied: list[str] = []
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            done = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
            for path in sorted(MIGRATIONS.glob("*.sql")):
                if path.stem in done:
                    continue
                connection.executescript(path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations(version,applied_at) VALUES (?,datetime('now'))",
                    (path.stem,),
                )
                applied.append(path.stem)
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
