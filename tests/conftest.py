from __future__ import annotations

import pytest

from fastclm.database import Database, set_database
from fastclm.services.identity import IdentityService


@pytest.fixture
def fresh_db(tmp_path):
    database = Database(tmp_path / "fastclm.sqlite")
    database.migrate()
    set_database(database)
    yield database
    set_database(None)


@pytest.fixture
def workspace(fresh_db):
    identity = IdentityService()
    user, organisation = identity.create_workspace("owner@example.test", "A-secure-passphrase1!", "Owner", "Example Studio")
    actor = identity.actor(user["id"], organisation["id"])
    return actor, user, organisation
