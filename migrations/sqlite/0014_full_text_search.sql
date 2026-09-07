CREATE VIRTUAL TABLE contract_search USING fts5(
    contract_id UNINDEXED,
    organisation_id UNINDEXED,
    title,
    reference,
    counterparty,
    body,
    tokenize='unicode61 remove_diacritics 2'
);
