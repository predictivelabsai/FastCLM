ALTER TABLE assistant_threads ADD COLUMN memory_summary TEXT NOT NULL DEFAULT '';

CREATE TABLE assistant_thread_contracts (
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    thread_id TEXT NOT NULL REFERENCES assistant_threads(id) ON DELETE CASCADE,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (thread_id, contract_id)
);

CREATE TABLE skill_tests (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    skill_version INTEGER NOT NULL,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    prompt TEXT NOT NULL,
    expected_outcome TEXT NOT NULL,
    observed_output TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('pass','fail','needs_review')),
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_thread_contracts_org ON assistant_thread_contracts(organisation_id, thread_id);
CREATE INDEX idx_skill_tests_skill_created ON skill_tests(organisation_id, skill_id, created_at DESC);
