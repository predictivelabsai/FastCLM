from __future__ import annotations

import sqlite3

from fastclm.config import settings
from fastclm.database import Database


def test_sqlite_upgrade_assigns_stable_sequences_to_existing_conversation(tmp_path):
    path = tmp_path / "upgrade.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    migration_paths = sorted((settings.root / "migrations" / "sqlite").glob("*.sql"))[:14]
    for migration in migration_paths:
        connection.executescript(migration.read_text(encoding="utf-8"))
        connection.execute("INSERT INTO schema_migrations(version,applied_at) VALUES (?,?)", (migration.stem, "2026-09-08T00:00:00+00:00"))
    connection.execute("INSERT INTO organisations(id,name,slug,created_at) VALUES ('org','Studio','studio','2026-09-08T00:00:00+00:00')")
    connection.execute("INSERT INTO users(id,email,name,created_at) VALUES ('user','owner@example.test','Owner','2026-09-08T00:00:00+00:00')")
    connection.execute("INSERT INTO assistant_threads(id,organisation_id,created_by,title,created_at,updated_at) VALUES ('thread','org','user','Matter','2026-09-08T00:00:00+00:00','2026-09-08T00:00:00+00:00')")
    connection.execute("INSERT INTO assistant_messages(id,organisation_id,thread_id,user_id,role,content,created_at) VALUES ('first','org','thread','user','user','First','2026-09-08T00:00:00+00:00')")
    connection.execute("INSERT INTO assistant_messages(id,organisation_id,thread_id,user_id,role,content,created_at) VALUES ('second','org','thread','user','assistant','Second','2026-09-08T00:00:00+00:00')")
    connection.commit()
    connection.close()

    database = Database(path)
    assert database.migrate() == ["0015_legal_content_governance"]
    assert database.rows("SELECT id,sequence_number FROM assistant_messages ORDER BY sequence_number") == [
        {"id": "first", "sequence_number": 1},
        {"id": "second", "sequence_number": 2},
    ]
    assert database.scalar("SELECT next_message_sequence FROM assistant_threads WHERE id='thread'") == 3
