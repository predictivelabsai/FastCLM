CREATE TABLE approval_policies (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    contract_type TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organisation_id, name)
);

CREATE TABLE approval_policy_stages (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    policy_id TEXT NOT NULL REFERENCES approval_policies(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    allowed_roles_json TEXT NOT NULL DEFAULT '["owner","admin","approver"]',
    required_approvals INTEGER NOT NULL DEFAULT 1 CHECK (required_approvals > 0),
    allow_requester INTEGER NOT NULL DEFAULT 1 CHECK (allow_requester IN (0,1)),
    require_distinct_prior INTEGER NOT NULL DEFAULT 0 CHECK (require_distinct_prior IN (0,1)),
    created_at TEXT NOT NULL,
    UNIQUE (policy_id, position)
);

CREATE TABLE contract_approval_runs (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    policy_id TEXT NOT NULL REFERENCES approval_policies(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','approved','changes_requested','cancelled')),
    current_stage_position INTEGER NOT NULL DEFAULT 1,
    initiated_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE approval_stage_assignments (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES contract_approval_runs(id) ON DELETE CASCADE,
    stage_id TEXT NOT NULL REFERENCES approval_policy_stages(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    assigned_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, stage_id, user_id)
);

CREATE TABLE approval_stage_decisions (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES contract_approval_runs(id) ON DELETE CASCADE,
    stage_id TEXT NOT NULL REFERENCES approval_policy_stages(id) ON DELETE RESTRICT,
    actor_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    represented_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    decision TEXT NOT NULL CHECK (decision IN ('approved','changes_requested')),
    comment TEXT NOT NULL DEFAULT '',
    decided_at TEXT NOT NULL,
    UNIQUE (run_id, stage_id, represented_user_id)
);

CREATE TABLE approval_delegations (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    delegator_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    delegate_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    CHECK (delegator_user_id <> delegate_user_id)
);

CREATE INDEX idx_approval_policies_org ON approval_policies(organisation_id, active, contract_type);
CREATE INDEX idx_approval_stages_policy ON approval_policy_stages(policy_id, position);
CREATE INDEX idx_approval_runs_contract ON contract_approval_runs(organisation_id, contract_id, status, created_at);
CREATE INDEX idx_approval_decisions_run ON approval_stage_decisions(organisation_id, run_id, stage_id, decided_at);
CREATE UNIQUE INDEX idx_approval_decisions_actor ON approval_stage_decisions(run_id, stage_id, actor_user_id);
CREATE INDEX idx_approval_delegations_window ON approval_delegations(organisation_id, delegate_user_id, active, starts_at, ends_at);
