from __future__ import annotations

import hashlib
import re

import pytest
from starlette.testclient import TestClient

from fastclm.services.identity import IdentityService


def test_invitation_acceptance_role_changes_and_owner_boundary(workspace, fresh_db):
    actor, _, _ = workspace
    identity = IdentityService()
    invitation, invitation_token = identity.invite(actor, "legal@example.test", "legal", ttl_seconds=3600)
    stored = fresh_db.one("SELECT token_hash FROM team_invitations WHERE id=?", (invitation["id"],))
    assert stored["token_hash"] == hashlib.sha256(invitation_token.encode()).hexdigest()
    assert invitation_token not in stored["token_hash"]
    assert identity.invitation(invitation_token)["organisation_id"] == actor.organisation_id

    user, organisation = identity.accept_invitation(invitation_token, name="Legal User", password="Secure-passphrase2!")
    invited_actor = identity.actor(user["id"], organisation["id"])
    assert invited_actor.role == "legal"
    assert identity.invitation(invitation_token) is None

    identity.update_role(actor, user["id"], "approver")
    assert identity.actor(user["id"], organisation["id"]).role == "approver"
    with pytest.raises(ValueError, match="owner role"):
        identity.update_role(actor, actor.user_id, "admin")
    with pytest.raises(ValueError, match="owner cannot"):
        identity.remove_member(actor, actor.user_id)
    identity.remove_member(actor, user["id"])
    with pytest.raises(LookupError):
        identity.actor(user["id"], organisation["id"])
    actions = {row["action"] for row in fresh_db.rows("SELECT action FROM audit_events WHERE organisation_id=?", (actor.organisation_id,))}
    assert {"team.invitation.created", "team.invitation.accepted", "team.member.role_changed", "team.member.removed"} <= actions


def test_existing_user_accepts_second_workspace_and_switches_session(fresh_db):
    identity = IdentityService()
    first_user, first_org = identity.create_workspace("first@example.test", "Secure-passphrase1!", "First", "First Studio")
    second_user, second_org = identity.create_workspace("second@example.test", "Secure-passphrase2!", "Second", "Second Studio")
    first_actor = identity.actor(first_user["id"], first_org["id"])
    _, invitation_token = identity.invite(first_actor, second_user["email"], "member")
    identity.accept_invitation(invitation_token, user_id=second_user["id"])
    assert len(identity.memberships(second_user["id"])) == 2

    from web_app import app
    with TestClient(app) as client:
        response = client.post("/login", data={"email": second_user["email"], "password": "Secure-passphrase2!"})
        assert second_org["name"] in response.text
        settings_page = client.get("/settings")
        csrf = re.search(r'name="csrf" value="([^"]+)"', settings_page.text).group(1)
        switched = client.post("/organisations/switch", data={"csrf": csrf, "organisation_id": first_org["id"]})
        assert switched.url.path == "/app"
        assert first_org["name"] in switched.text


def test_revoked_invitation_cannot_be_accepted(workspace):
    actor, _, _ = workspace
    identity = IdentityService()
    invitation, invitation_token = identity.invite(actor, "revoked@example.test", "member")
    identity.revoke_invitation(actor, invitation["id"])
    assert identity.invitation(invitation_token) is None
    with pytest.raises(ValueError, match="invalid, expired, or already used"):
        identity.accept_invitation(invitation_token, name="Revoked", password="Secure-passphrase3!")


def test_new_user_accepts_invitation_from_public_route(workspace, fresh_db):
    actor, _, organisation = workspace
    _, invitation_token = IdentityService().invite(actor, "new-member@example.test", "member")
    from web_app import app

    with TestClient(app) as client:
        page = client.get(f"/invitations/{invitation_token}")
        assert page.status_code == 200
        assert f"Join {organisation['name']}" in page.text
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        accepted = client.post("/invitations/actions/accept", data={
            "csrf": csrf, "token": invitation_token, "name": "New Member", "password": "Secure-passphrase4!",
        })
        assert accepted.url.path == "/app"
        assert organisation["name"] in accepted.text
    user = fresh_db.one("SELECT id FROM users WHERE email='new-member@example.test'")
    assert IdentityService().actor(user["id"], organisation["id"]).role == "member"
