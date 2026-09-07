CREATE TABLE legal_review_requests (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    jurisdiction TEXT NOT NULL,
    clause_ids_json TEXT NOT NULL DEFAULT '[]',
    reviewer_name TEXT NOT NULL DEFAULT '',
    reviewer_email TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','completed','cancelled')),
    requested_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    closed_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    closed_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE clause_legal_reviews (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    clause_id TEXT NOT NULL REFERENCES clauses(id) ON DELETE CASCADE,
    request_id TEXT REFERENCES legal_review_requests(id) ON DELETE SET NULL,
    wording_checksum TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved','changes_requested','not_approved')),
    reviewed_jurisdiction TEXT NOT NULL,
    reviewer_name TEXT NOT NULL,
    reviewer_organisation TEXT NOT NULL,
    reviewer_qualification TEXT NOT NULL,
    evidence_reference TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    qualification_attested INTEGER NOT NULL CHECK (qualification_attested = 1),
    recorded_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_legal_review_requests_org ON legal_review_requests(organisation_id, status, created_at);
CREATE INDEX idx_clause_legal_reviews_clause ON clause_legal_reviews(organisation_id, clause_id, created_at);

ALTER TABLE assistant_threads ADD COLUMN next_message_sequence INTEGER NOT NULL DEFAULT 1;
ALTER TABLE assistant_messages ADD COLUMN sequence_number INTEGER NOT NULL DEFAULT 0;

WITH ranked AS (
    SELECT id, row_number() OVER (PARTITION BY thread_id ORDER BY created_at,id) AS sequence_number
    FROM assistant_messages
)
UPDATE assistant_messages
SET sequence_number=ranked.sequence_number
FROM ranked
WHERE assistant_messages.id=ranked.id;

UPDATE assistant_threads
SET next_message_sequence = COALESCE((
    SELECT MAX(sequence_number) + 1 FROM assistant_messages WHERE thread_id=assistant_threads.id
), 1);

CREATE UNIQUE INDEX idx_assistant_messages_thread_sequence ON assistant_messages(thread_id, sequence_number);
