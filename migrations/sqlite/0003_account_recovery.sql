ALTER TABLE users ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 1;

CREATE TABLE auth_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL CHECK (purpose IN ('verify','reset')),
    token_hash TEXT NOT NULL UNIQUE,
    expires_at INTEGER NOT NULL,
    used_at INTEGER,
    created_at INTEGER NOT NULL
);

CREATE INDEX idx_auth_tokens_user_purpose ON auth_tokens(user_id, purpose);
