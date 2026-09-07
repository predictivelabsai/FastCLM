"""Application-encrypted, tenant-scoped workspace backup archives."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

from cryptography.fernet import Fernet

from fastclm.config import settings
from fastclm.database import get_database
from fastclm.security import Actor
from fastclm.services.audit import AuditService
from fastclm.services.identity import new_id, now
from fastclm.storage import get_storage


def _fernet() -> Fernet:
    configured = settings.backup_key or settings.encryption_key
    if configured:
        try:
            return Fernet(configured.encode())
        except ValueError:
            pass
    material = configured or settings.secret
    key = base64.urlsafe_b64encode(hashlib.sha256(("fastclm-backup:" + material).encode()).digest())
    return Fernet(key)


def decrypt_backup(content: bytes) -> bytes:
    """Decrypt an archive for disaster recovery tooling and verification tests."""
    return _fernet().decrypt(content)


class BackupService:
    def list(self, actor: Actor) -> list[dict]:
        actor.require("team.manage")
        return get_database().rows(
            "SELECT * FROM organisation_backups WHERE organisation_id=? ORDER BY created_at DESC LIMIT 20",
            (actor.organisation_id,),
        )

    def _tables(self, organisation_id: str) -> dict[str, list[dict]]:
        database = get_database()
        names = database.rows(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT IN ('schema_migrations','organisation_backups') ORDER BY name"
        )
        exported: dict[str, list[dict]] = {}
        for item in names:
            name = item["name"]
            columns = {column["name"] for column in database.rows(f'PRAGMA table_info("{name}")')}
            if "organisation_id" in columns:
                exported[name] = database.rows(f'SELECT * FROM "{name}" WHERE organisation_id=?', (organisation_id,))
        exported["organisations"] = database.rows("SELECT * FROM organisations WHERE id=?", (organisation_id,))
        exported["users"] = database.rows(
            "SELECT u.id,u.email,u.name,u.created_at FROM users u JOIN memberships m ON m.user_id=u.id WHERE m.organisation_id=?",
            (organisation_id,),
        )
        return exported

    def create(self, actor: Actor) -> dict:
        actor.require("team.manage")
        backup_id, created = new_id(), now()
        tables = self._tables(actor.organisation_id)
        manifest = {
            "format": "fastclm-workspace-backup-v1",
            "organisation_id": actor.organisation_id,
            "created_at": created,
            "tables": {name: len(rows) for name, rows in tables.items()},
        }
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
            archive.writestr("records.json", json.dumps(tables, ensure_ascii=False, sort_keys=True, default=str))
            versions = tables.get("contract_versions", [])
            for version in versions:
                if not version["storage_path"] or version.get("attachment_purged_at"):
                    continue
                content = get_storage(version.get("storage_backend") or "local", settings).get(version["storage_path"])
                if version.get("source_checksum") and hashlib.sha256(content).hexdigest() != version["source_checksum"]:
                    raise ValueError(f"Attachment integrity failed for version {version['id']}")
                filename = Path(version["source_filename"] or "source.bin").name
                archive.writestr(f"attachments/{version['id']}/{filename}", content)
        encrypted = _fernet().encrypt(archive_buffer.getvalue())
        checksum = hashlib.sha256(encrypted).hexdigest()
        storage = get_storage(config=settings)
        storage_path = f"{actor.organisation_id}/backups/{backup_id}.fastclm.enc"
        storage.put(storage_path, encrypted, "application/octet-stream")
        try:
            with get_database().transaction() as tx:
                tx.execute(
                    "INSERT INTO organisation_backups(id,organisation_id,storage_backend,storage_path,checksum,byte_size,status,created_by,created_at) VALUES (?,?,?,?,?,?,'complete',?,?)",
                    (backup_id, actor.organisation_id, storage.name, storage_path, checksum, len(encrypted), actor.user_id, created),
                )
                AuditService().record(actor, "organisation_backup", backup_id, "backup.created", {"checksum": checksum, "byte_size": len(encrypted)}, tx)
        except Exception:
            storage.delete(storage_path)
            raise
        return get_database().one("SELECT * FROM organisation_backups WHERE id=?", (backup_id,))

    def content(self, actor: Actor, backup_id: str) -> tuple[dict, bytes]:
        actor.require("team.manage")
        item = get_database().one(
            "SELECT * FROM organisation_backups WHERE id=? AND organisation_id=? AND status='complete'",
            (backup_id, actor.organisation_id),
        )
        if not item:
            raise LookupError("Backup not found")
        content = get_storage(item["storage_backend"], settings).get(item["storage_path"])
        if hashlib.sha256(content).hexdigest() != item["checksum"]:
            raise ValueError("Backup integrity check failed")
        return item, content
