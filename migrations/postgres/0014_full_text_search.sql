CREATE TABLE contract_search (
    contract_id TEXT PRIMARY KEY REFERENCES contracts(id) ON DELETE CASCADE,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    reference TEXT NOT NULL DEFAULT '',
    counterparty TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    search_vector tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(reference, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(counterparty, '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(body, '')), 'C')
    ) STORED
);

CREATE INDEX idx_contract_search_org ON contract_search(organisation_id);
CREATE INDEX idx_contract_search_vector ON contract_search USING GIN(search_vector);
