"""Transparent, organisation-scoped assistant skills with immutable versions."""
from __future__ import annotations

from fastclm.database import get_database
from fastclm.security import Actor
from fastclm.services.audit import AuditService
from fastclm.services.identity import new_id, now


STARTER_SKILLS = (
    (
        "contract-qa",
        "Contract Q&A",
        "Answer focused questions from selected agreements and cite the source version.",
        """# Contract Q&A

Lead with the direct answer. Use only the supplied contract sources as evidence. Quote sparingly and cite every substantive conclusion with the source number. If the document does not answer the question, say so. Distinguish contract wording from interpretation and do not give legal advice.
""",
    ),
    (
        "contract-snapshot",
        "Contract snapshot",
        "Produce a concise commercial summary, dates, obligations, risks, and open decisions.",
        """# Contract snapshot

Summarise the parties, purpose, value, term, renewal, termination, liability, data protection, intellectual property, and governing law. Finish with dated obligations and open decisions. Cite each finding to the supplied source and clearly label missing or ambiguous terms.
""",
    ),
    (
        "commercial-review",
        "UK / EU commercial review",
        "Review a commercial agreement against generic UK/EU SME considerations.",
        """# UK / EU commercial review

Review liability, indemnities, termination, renewal, payment, confidentiality, data protection, IP, assignment, governing law, and operational obligations. Separate high, medium, and low attention items. This is generic assistive analysis, not jurisdiction-specific legal advice. Never approve or change the contract.
""",
    ),
    (
        "obligation-extractor",
        "Obligation extractor",
        "Find dated or recurring duties and propose tracked obligations for human confirmation.",
        """# Obligation extractor

Identify who must do what, by when, under which clause, and whether it repeats. Cite the source. If a due date depends on an event, preserve that dependency rather than inventing a calendar date. Propose obligation records, but never create them without explicit human confirmation.
""",
    ),
    (
        "skill-creator",
        "Skill Creator",
        "Use conversation to design, test, and propose a reusable legal workflow skill.",
        """# Skill Creator

Help the user turn their legal workflow into a reusable skill through conversation, not a form. Establish the purpose, trigger phrases, required inputs, workflow, output format, legal boundaries, and at least one concrete example. Ask one focused question at a time when material details are missing. Never invent the user's legal positions.

When the user has supplied enough detail, draft complete Markdown instructions and use the create_skill proposal tool. The skill is not saved until the user reviews and confirms the proposal.
""",
    ),
)


class SkillService:
    def seed(self, organisation_id: str, user_id: str) -> None:
        created = now()
        with get_database().transaction() as tx:
            for slug, name, description, instructions in STARTER_SKILLS:
                if tx.one("SELECT id FROM skills WHERE organisation_id=? AND slug=?", (organisation_id, slug)):
                    continue
                skill_id = new_id()
                values = (skill_id, organisation_id, slug, name, description, instructions, user_id, user_id, created, created)
                tx.execute(
                    "INSERT INTO skills(id,organisation_id,slug,name,description,instructions,created_by,updated_by,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    values,
                )
                tx.execute(
                    "INSERT INTO skill_versions(id,organisation_id,skill_id,version_number,name,description,instructions,jurisdiction,created_by,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), organisation_id, skill_id, 1, name, description, instructions, "UK / EU", user_id, created),
                )

    def by_slug(self, actor: Actor, slug: str) -> dict | None:
        actor.require("assistant.use")
        row = get_database().one("SELECT id FROM skills WHERE organisation_id=? AND slug=? AND status='active'", (actor.organisation_id, slug))
        return self.get(actor, row["id"]) if row else None

    def list(self, actor: Actor, include_archived: bool = False) -> list[dict]:
        actor.require("assistant.use")
        where = "organisation_id=?" + ("" if include_archived else " AND status<>'archived'")
        return get_database().rows(f"SELECT * FROM skills WHERE {where} ORDER BY name", (actor.organisation_id,))

    def get(self, actor: Actor, skill_id: str) -> dict:
        actor.require("assistant.use")
        row = get_database().one("SELECT * FROM skills WHERE id=? AND organisation_id=?", (skill_id, actor.organisation_id))
        if not row:
            raise LookupError("Skill not found")
        row["versions"] = get_database().rows(
            "SELECT v.*,u.name author_name FROM skill_versions v LEFT JOIN users u ON u.id=v.created_by "
            "WHERE v.skill_id=? AND v.organisation_id=? ORDER BY v.version_number DESC",
            (skill_id, actor.organisation_id),
        )
        return row

    def create(self, actor: Actor, data: dict) -> dict:
        actor.require("skills.manage")
        name = str(data.get("name", "")).strip()
        description = str(data.get("description", "")).strip()
        instructions = str(data.get("instructions", "")).strip()
        if not name or not description or not instructions:
            raise ValueError("Name, description, and instructions are required")
        slug = "-".join(name.lower().split())[:64]
        skill_id, created = new_id(), now()
        with get_database().transaction() as tx:
            tx.execute(
                "INSERT INTO skills(id,organisation_id,slug,name,description,instructions,jurisdiction,created_by,updated_by,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (skill_id, actor.organisation_id, slug, name, description, instructions, str(data.get("jurisdiction", "UK / EU")), actor.user_id, actor.user_id, created, created),
            )
            tx.execute(
                "INSERT INTO skill_versions(id,organisation_id,skill_id,version_number,name,description,instructions,jurisdiction,created_by,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_id(), actor.organisation_id, skill_id, 1, name, description, instructions, str(data.get("jurisdiction", "UK / EU")), actor.user_id, created),
            )
            AuditService().record(actor, "skill", skill_id, "skill.created", {"slug": slug, "version": 1}, tx)
        return self.get(actor, skill_id)

    def update(self, actor: Actor, skill_id: str, data: dict) -> dict:
        actor.require("skills.manage")
        current = self.get(actor, skill_id)
        name = str(data.get("name", "")).strip()
        description = str(data.get("description", "")).strip()
        instructions = str(data.get("instructions", "")).strip()
        jurisdiction = str(data.get("jurisdiction", "UK / EU")).strip() or "UK / EU"
        if not name or not description or not instructions:
            raise ValueError("Name, description, and instructions are required")
        version = int(current["current_version"]) + 1
        updated = now()
        with get_database().transaction() as tx:
            result = tx.execute(
                "UPDATE skills SET name=?,description=?,instructions=?,jurisdiction=?,current_version=?,updated_by=?,updated_at=? "
                "WHERE id=? AND organisation_id=?",
                (name, description, instructions, jurisdiction, version, actor.user_id, updated, skill_id, actor.organisation_id),
            )
            if result.rowcount != 1:
                raise LookupError("Skill not found")
            tx.execute(
                "INSERT INTO skill_versions(id,organisation_id,skill_id,version_number,name,description,instructions,jurisdiction,created_by,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_id(), actor.organisation_id, skill_id, version, name, description, instructions, jurisdiction, actor.user_id, updated),
            )
            AuditService().record(actor, "skill", skill_id, "skill.version.created", {"version": version}, tx)
        return self.get(actor, skill_id)
