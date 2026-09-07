ALTER TABLE signature_requests ADD COLUMN source_version_id TEXT REFERENCES contract_versions(id) ON DELETE SET NULL;
ALTER TABLE signature_requests ADD COLUMN dispatch_confirmed_by TEXT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE signature_requests ADD COLUMN dispatched_at TEXT NOT NULL DEFAULT '';
ALTER TABLE signature_requests ADD COLUMN completed_at TEXT NOT NULL DEFAULT '';
ALTER TABLE signature_requests ADD COLUMN completed_storage_backend TEXT NOT NULL DEFAULT '';
ALTER TABLE signature_requests ADD COLUMN completed_storage_path TEXT NOT NULL DEFAULT '';
ALTER TABLE signature_requests ADD COLUMN completed_checksum TEXT NOT NULL DEFAULT '';
ALTER TABLE signature_requests ADD COLUMN completed_media_type TEXT NOT NULL DEFAULT '';
ALTER TABLE signature_requests ADD COLUMN webhook_verified_at TEXT NOT NULL DEFAULT '';

CREATE TABLE signature_events (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    signature_request_id TEXT NOT NULL REFERENCES signature_requests(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('docusign','signwell')),
    external_event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    verified INTEGER NOT NULL CHECK (verified IN (0,1)),
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    received_at TEXT NOT NULL,
    UNIQUE (provider, external_event_id)
);

CREATE TABLE signature_recipients (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    signature_request_id TEXT NOT NULL REFERENCES signature_requests(id) ON DELETE CASCADE,
    provider_recipient_id TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'sent',
    signed_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE (signature_request_id, provider_recipient_id)
);

CREATE INDEX idx_signature_events_request ON signature_events(organisation_id, signature_request_id, received_at);
CREATE INDEX idx_signature_recipients_request ON signature_recipients(organisation_id, signature_request_id, status);
