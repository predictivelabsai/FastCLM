CREATE TABLE notification_templates (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    template_key TEXT NOT NULL CHECK (template_key IN ('due_soon','overdue','escalation')),
    name TEXT NOT NULL,
    subject_template TEXT NOT NULL,
    body_template TEXT NOT NULL,
    postmark_alias TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organisation_id, template_key)
);

CREATE TABLE reminder_preferences (
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    due_soon_days INTEGER NOT NULL DEFAULT 14 CHECK (due_soon_days BETWEEN 0 AND 90),
    overdue_repeat_days INTEGER NOT NULL DEFAULT 1 CHECK (overdue_repeat_days BETWEEN 1 AND 30),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (organisation_id, user_id)
);

CREATE TABLE reminder_escalation_rules (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    overdue_days INTEGER NOT NULL CHECK (overdue_days BETWEEN 0 AND 365),
    recipient_role TEXT NOT NULL DEFAULT '' CHECK (recipient_role IN ('','owner','admin','legal','approver','member')),
    recipient_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    template_id TEXT NOT NULL REFERENCES notification_templates(id) ON DELETE RESTRICT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    CHECK (recipient_role <> '' OR recipient_user_id IS NOT NULL)
);

ALTER TABLE reminder_deliveries ADD COLUMN template_id TEXT REFERENCES notification_templates(id) ON DELETE SET NULL;
ALTER TABLE reminder_deliveries ADD COLUMN escalation_rule_id TEXT REFERENCES reminder_escalation_rules(id) ON DELETE SET NULL;
ALTER TABLE reminder_deliveries ADD COLUMN recipient_user_id TEXT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE reminder_deliveries ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 1;

CREATE INDEX idx_notification_templates_org ON notification_templates(organisation_id, template_key, active);
CREATE INDEX idx_reminder_rules_org ON reminder_escalation_rules(organisation_id, active, overdue_days);
