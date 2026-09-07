# PostgreSQL migrations

FastCLM applies the numbered dialect-neutral SQLite migrations to PostgreSQL,
translating placeholders and the one binary column type. A same-numbered file
in this directory overrides a dialect-specific migration. Full-text search is
the first override: PostgreSQL uses a generated weighted `tsvector` plus GIN,
while SQLite keeps its FTS5 index. Migration version parity is enforced by the
shared `schema_migrations` ledger.
