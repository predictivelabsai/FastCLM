CREATE TABLE organisations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    password_hash TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE memberships (
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('owner','admin','legal','approver','member')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (organisation_id, user_id)
);

CREATE TABLE counterparties (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    registration_number TEXT NOT NULL DEFAULT '',
    jurisdiction TEXT NOT NULL DEFAULT '',
    contact_name TEXT NOT NULL DEFAULT '',
    contact_email TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (organisation_id, name)
);

CREATE TABLE contracts (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    counterparty_id TEXT REFERENCES counterparties(id) ON DELETE SET NULL,
    owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    reference TEXT NOT NULL,
    title TEXT NOT NULL,
    contract_type TEXT NOT NULL DEFAULT 'Commercial agreement',
    jurisdiction TEXT NOT NULL DEFAULT 'England and Wales',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','review','approval','signature','active','expired','terminated')),
    risk_level TEXT NOT NULL DEFAULT 'unreviewed' CHECK (risk_level IN ('unreviewed','low','medium','high')),
    summary TEXT NOT NULL DEFAULT '',
    value_amount TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT 'GBP',
    effective_date TEXT NOT NULL DEFAULT '',
    expiry_date TEXT NOT NULL DEFAULT '',
    notice_date TEXT NOT NULL DEFAULT '',
    renewal_type TEXT NOT NULL DEFAULT 'none' CHECK (renewal_type IN ('none','manual','automatic')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organisation_id, reference)
);

CREATE TABLE contract_blocks (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    block_type TEXT NOT NULL CHECK (block_type IN ('heading','paragraph','list','quote','clause')),
    content TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE contract_versions (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    body_text TEXT NOT NULL DEFAULT '',
    content_json TEXT NOT NULL DEFAULT '[]',
    source_filename TEXT NOT NULL DEFAULT '',
    storage_path TEXT NOT NULL DEFAULT '',
    media_type TEXT NOT NULL DEFAULT '',
    byte_size INTEGER NOT NULL DEFAULT 0,
    checksum TEXT NOT NULL,
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    UNIQUE (contract_id, version_number)
);

CREATE TABLE obligations (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    due_date TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','complete','waived')),
    recurrence TEXT NOT NULL DEFAULT 'none' CHECK (recurrence IN ('none','monthly','quarterly','annual')),
    completed_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE approvals (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    approver_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    decision TEXT NOT NULL CHECK (decision IN ('approved','changes_requested')),
    comment TEXT NOT NULL DEFAULT '',
    decided_at TEXT NOT NULL
);

CREATE TABLE clauses (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'General',
    jurisdiction TEXT NOT NULL DEFAULT 'UK / EU',
    body TEXT NOT NULL,
    fallback_body TEXT NOT NULL DEFAULT '',
    risk_guidance TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE review_findings (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    source TEXT NOT NULL CHECK (source IN ('deterministic','xai')),
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low','medium','high')),
    findings_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE user_provider_credentials (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    api_key_enc BLOB NOT NULL,
    api_key_hint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, provider)
);

CREATE TABLE user_ai_allowances (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    platform_queries_used INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE signature_requests (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('docusign','signwell')),
    external_id TEXT NOT NULL DEFAULT '',
    recipient_name TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    request_json TEXT NOT NULL DEFAULT '{}',
    response_json TEXT NOT NULL DEFAULT '{}',
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE audit_events (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX idx_contracts_org_status ON contracts(organisation_id, status);
CREATE INDEX idx_contracts_org_dates ON contracts(organisation_id, expiry_date, notice_date);
CREATE INDEX idx_blocks_contract ON contract_blocks(contract_id, position);
CREATE INDEX idx_versions_contract ON contract_versions(contract_id, version_number DESC);
CREATE INDEX idx_obligations_org_due ON obligations(organisation_id, status, due_date);
CREATE INDEX idx_audit_org_created ON audit_events(organisation_id, created_at DESC);
