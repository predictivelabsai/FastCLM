"""Dialect-native full-text contract indexing and search."""
from __future__ import annotations

import re

from fastclm.database import get_database
from fastclm.security import Actor


class SearchService:
    def reindex(self, actor: Actor) -> int:
        actor.require("contracts.view")
        database = get_database()
        rows = database.rows(
            "SELECT c.id,c.title,c.reference,COALESCE(p.name,'') counterparty FROM contracts c "
            "LEFT JOIN counterparties p ON p.id=c.counterparty_id AND p.organisation_id=c.organisation_id "
            "WHERE c.organisation_id=? ORDER BY c.id",
            (actor.organisation_id,),
        )
        with database.transaction() as tx:
            tx.execute("DELETE FROM contract_search WHERE organisation_id=?", (actor.organisation_id,))
            for row in rows:
                blocks = tx.rows("SELECT content FROM contract_blocks WHERE contract_id=? AND organisation_id=? ORDER BY position", (row["id"], actor.organisation_id))
                body = "\n".join(block["content"] for block in blocks)
                tx.execute(
                    "INSERT INTO contract_search(contract_id,organisation_id,title,reference,counterparty,body) VALUES (?,?,?,?,?,?)",
                    (row["id"], actor.organisation_id, row["title"], row["reference"], row["counterparty"], body),
                )
        return len(rows)

    def search(self, actor: Actor, query: str, limit: int = 200) -> list[str]:
        actor.require("contracts.view")
        tokens = re.findall(r"\w+", query.casefold(), re.UNICODE)
        if not tokens:
            return []
        self.reindex(actor)
        database = get_database()
        if database.dialect == "postgresql":
            expression = " & ".join(f"{token}:*" for token in tokens[:12])
            rows = database.rows(
                "SELECT contract_id FROM contract_search WHERE organisation_id=? AND search_vector @@ to_tsquery('simple', ?) "
                "ORDER BY ts_rank(search_vector, to_tsquery('simple', ?)) DESC LIMIT ?",
                (actor.organisation_id, expression, expression, limit),
            )
        else:
            expression = " AND ".join(f'"{token}"*' for token in tokens[:12])
            rows = database.rows(
                "SELECT contract_id FROM contract_search WHERE contract_search MATCH ? AND organisation_id=? ORDER BY bm25(contract_search,0,0,10,10,5,1) LIMIT ?",
                (expression, actor.organisation_id, limit),
            )
        return [row["contract_id"] for row in rows]
