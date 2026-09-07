from __future__ import annotations

import os
import uuid

import pytest

from fastclm.database import Database, set_database
from fastclm.services.identity import IdentityService


@pytest.fixture
def fresh_db(tmp_path):
    postgres_url = os.getenv("FASTCLM_TEST_POSTGRES_URL", "").strip()
    database_name = ""
    if postgres_url:
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import conninfo_to_dict, make_conninfo

        database_name = "fastclm_test_" + uuid.uuid4().hex
        with psycopg.connect(postgres_url, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        parameters = conninfo_to_dict(postgres_url)
        parameters["dbname"] = database_name
        database = Database(database_url=make_conninfo(**parameters))
    else:
        database = Database(tmp_path / "fastclm.sqlite")
    database.migrate()
    set_database(database)
    yield database
    set_database(None)
    if database_name:
        import psycopg
        from psycopg import sql

        with psycopg.connect(postgres_url, autocommit=True) as admin:
            admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", (database_name,))
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


@pytest.fixture
def workspace(fresh_db):
    identity = IdentityService()
    user, organisation = identity.create_workspace("owner@example.test", "A-secure-passphrase1!", "Owner", "Example Studio")
    actor = identity.actor(user["id"], organisation["id"])
    return actor, user, organisation
