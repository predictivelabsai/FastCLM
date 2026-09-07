ALTER TABLE organisations ADD COLUMN retention_enabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE organisations ADD COLUMN retention_days INTEGER NOT NULL DEFAULT 2555;

ALTER TABLE contract_versions ADD COLUMN storage_backend TEXT NOT NULL DEFAULT 'local';
ALTER TABLE contract_versions ADD COLUMN page_text_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE contract_versions ADD COLUMN ocr_applied INTEGER NOT NULL DEFAULT 0;
ALTER TABLE contract_versions ADD COLUMN malware_scan_status TEXT NOT NULL DEFAULT 'clean';
ALTER TABLE contract_versions ADD COLUMN malware_scanner TEXT NOT NULL DEFAULT 'builtin';
ALTER TABLE contract_versions ADD COLUMN attachment_purged_at TEXT NOT NULL DEFAULT '';
ALTER TABLE contract_versions ADD COLUMN attachment_purge_reason TEXT NOT NULL DEFAULT '';

CREATE TABLE organisation_backups (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    storage_backend TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    checksum TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('complete','failed')),
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_versions_retention ON contract_versions(organisation_id, attachment_purged_at, created_at);
CREATE INDEX idx_backups_org_created ON organisation_backups(organisation_id, created_at DESC);
