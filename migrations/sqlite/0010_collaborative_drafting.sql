CREATE TABLE contract_redlines (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    block_id TEXT REFERENCES contract_blocks(id) ON DELETE CASCADE,
    operation TEXT NOT NULL CHECK (operation IN ('insert','replace','delete')),
    original_text TEXT NOT NULL DEFAULT '',
    proposed_text TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','rejected')),
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    decided_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    decided_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE contract_comments (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    block_id TEXT REFERENCES contract_blocks(id) ON DELETE CASCADE,
    parent_id TEXT REFERENCES contract_comments(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    resolved_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE comment_mentions (
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    comment_id TEXT NOT NULL REFERENCES contract_comments(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (comment_id, user_id)
);

CREATE TABLE contract_assignments (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    comment_id TEXT REFERENCES contract_comments(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    assigned_to TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','complete','cancelled')),
    due_date TEXT NOT NULL DEFAULT '',
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE contract_templates (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    contract_type TEXT NOT NULL DEFAULT 'Commercial agreement',
    jurisdiction TEXT NOT NULL DEFAULT 'UK / EU',
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organisation_id, name)
);

CREATE TABLE contract_template_blocks (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    template_id TEXT NOT NULL REFERENCES contract_templates(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    block_type TEXT NOT NULL CHECK (block_type IN ('heading','paragraph','list','quote','clause')),
    content TEXT NOT NULL
);

CREATE TABLE negotiation_playbooks (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    contract_type TEXT NOT NULL DEFAULT 'Commercial agreement',
    jurisdiction TEXT NOT NULL DEFAULT 'UK / EU',
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organisation_id, name)
);

CREATE TABLE negotiation_playbook_clauses (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    playbook_id TEXT NOT NULL REFERENCES negotiation_playbooks(id) ON DELETE CASCADE,
    clause_id TEXT NOT NULL REFERENCES clauses(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    negotiation_note TEXT NOT NULL DEFAULT '',
    UNIQUE (playbook_id, clause_id)
);

CREATE INDEX idx_redlines_contract ON contract_redlines(organisation_id, contract_id, status, created_at);
CREATE INDEX idx_comments_contract ON contract_comments(organisation_id, contract_id, status, created_at);
CREATE INDEX idx_assignments_contract ON contract_assignments(organisation_id, contract_id, status, due_date);
CREATE INDEX idx_template_blocks ON contract_template_blocks(template_id, position);
CREATE INDEX idx_playbook_clauses ON negotiation_playbook_clauses(playbook_id, position);
