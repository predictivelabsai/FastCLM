CREATE TABLE team_invitations (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin','legal','approver','member')),
    token_hash TEXT NOT NULL UNIQUE,
    invited_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    expires_at INTEGER NOT NULL,
    accepted_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    accepted_at INTEGER,
    revoked_at INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_team_invitations_org_email
ON team_invitations(organisation_id, email, expires_at);

CREATE TABLE scim_identities (
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scim_id TEXT NOT NULL,
    external_id TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (organisation_id, user_id),
    UNIQUE (organisation_id, scim_id)
);

CREATE UNIQUE INDEX idx_scim_external_id
ON scim_identities(organisation_id, external_id)
WHERE external_id <> '';
