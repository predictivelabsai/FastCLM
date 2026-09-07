CREATE TABLE reminder_deliveries (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    obligation_id TEXT NOT NULL REFERENCES obligations(id) ON DELETE CASCADE,
    recipient_email TEXT NOT NULL,
    reminder_kind TEXT NOT NULL,
    delivery_date TEXT NOT NULL,
    provider_message_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (obligation_id, recipient_email, reminder_kind, delivery_date)
);
