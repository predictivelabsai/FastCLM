"""Non-authoritative deterministic and xAI-assisted contract review."""
from __future__ import annotations

import json
import re

import httpx

from fastclm.config import settings
from fastclm.database import get_database
from fastclm.security import Actor
from fastclm.services.audit import AuditService
from fastclm.services.contracts import ContractService, blocks_to_text
from fastclm.services.credentials import authorize, refund
from fastclm.services.identity import new_id, now


CHECKS = (
    ("Automatic renewal", r"auto(?:matic(?:ally)?)?[ -]?renew", "high", "Confirm renewal term and notice deadline."),
    ("Unlimited liability", r"unlimited liability|without limitation", "high", "Confirm the exposure is intended and approved."),
    ("Exclusivity", r"exclusive|exclusivity", "medium", "Check scope, duration, territory, and exit rights."),
    ("Personal data", r"personal data|data protection|gdpr", "medium", "Confirm roles, Article 28 terms, transfers, and security measures."),
    ("Governing law", r"governed by|governing law|jurisdiction", "low", "Confirm the governing law and dispute forum are explicit."),
    ("Termination", r"terminat", "low", "Check cure periods, convenience rights, exit support, and surviving obligations."),
    ("Assignment", r"assign(?:ment|ed)?", "medium", "Check consent rules and change-of-control treatment."),
)


def deterministic_findings(text: str) -> list[dict]:
    findings = []
    for title, pattern, severity, guidance in CHECKS:
        if re.search(pattern, text, re.IGNORECASE):
            findings.append({"title": title, "severity": severity, "guidance": guidance})
    present = {item["title"] for item in findings}
    if "Governing law" not in present:
        findings.append({"title": "Governing law not detected", "severity": "medium", "guidance": "Add or confirm a governing-law and forum clause."})
    if "Termination" not in present:
        findings.append({"title": "Termination terms not detected", "severity": "high", "guidance": "Add termination, cure, and post-termination provisions."})
    return findings


def _risk(findings: list[dict]) -> str:
    if any(item.get("severity") == "high" for item in findings):
        return "high"
    if any(item.get("severity") == "medium" for item in findings):
        return "medium"
    return "low"


class ReviewService:
    def review(self, actor: Actor, contract_id: str, *, use_ai: bool = False) -> dict:
        actor.require("contracts.view")
        contract = ContractService().get(actor, contract_id)
        text = blocks_to_text(contract["blocks"])
        if not text.strip():
            raise ValueError("Add or import contract text before review")
        source, findings = "deterministic", deterministic_findings(text)
        if use_ai:
            key, funding, reserved = authorize(actor.user_id)
            try:
                findings = self._xai(key, contract, text)
                source = f"xai:{funding}"
            except Exception:
                refund(actor.user_id, reserved)
                raise
        risk = _risk(findings)
        finding_id, created = new_id(), now()
        stored_source = "xai" if source.startswith("xai") else "deterministic"
        with get_database().transaction() as tx:
            tx.execute("INSERT INTO review_findings(id,organisation_id,contract_id,user_id,source,risk_level,findings_json,created_at) VALUES (?,?,?,?,?,?,?,?)", (finding_id, actor.organisation_id, contract_id, actor.user_id, stored_source, risk, json.dumps(findings), created))
            tx.execute("UPDATE contracts SET risk_level=?,updated_at=? WHERE id=? AND organisation_id=?", (risk, created, contract_id, actor.organisation_id))
            AuditService().record(actor, "contract", contract_id, "review.completed", {"source": source, "risk_level": risk, "finding_count": len(findings)}, tx)
        return {"id": finding_id, "source": source, "risk_level": risk, "findings": findings, "created_at": created}

    def _xai(self, key: str, contract: dict, text: str) -> list[dict]:
        prompt = (
            "You are a contract review assistant, not a lawyer or decision maker. Review the supplied agreement for a UK/EU SME. "
            "Return only a JSON array with objects containing title, severity (low|medium|high), guidance, and evidence. "
            "Cover liability, indemnities, termination, renewal, data protection, IP, confidentiality, payment, governing law, assignment, and missing terms. "
            "Be concise and do not claim legal certainty.\n\n"
            f"Title: {contract['title']}\nJurisdiction: {contract['jurisdiction']}\n\n{text[:60000]}"
        )
        response = httpx.post(
            f"{settings.xai_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": settings.xai_model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 1800},
            timeout=60,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE)
        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError("AI review returned an unexpected shape")
        clean = []
        for item in data[:20]:
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity", "medium")).lower()
            clean.append({
                "title": str(item.get("title", "Review point"))[:160],
                "severity": severity if severity in {"low", "medium", "high"} else "medium",
                "guidance": str(item.get("guidance", ""))[:1000],
                "evidence": str(item.get("evidence", ""))[:1000],
            })
        if not clean:
            raise ValueError("AI review returned no usable findings")
        return clean
