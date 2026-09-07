"""Environment-backed FastCLM configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _csv(name: str) -> tuple[str, ...]:
    return tuple(part.strip().lower() for part in os.getenv(name, "").split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    root: Path
    secret: str
    encryption_key: str
    port: int
    public_url: str
    environment: str
    data_dir: Path
    sqlite_path: Path
    upload_dir: Path
    storage_backend: str
    s3_bucket: str
    s3_endpoint_url: str
    s3_region: str
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_prefix: str
    s3_kms_key_id: str
    clamav_host: str
    clamav_port: int
    ocr_enabled: bool
    ocr_language: str
    backup_key: str
    allow_test_auth: bool
    require_email_verification: bool
    platform_admins: tuple[str, ...]
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    google_allowed_domains: tuple[str, ...]
    google_allowed_emails: tuple[str, ...]
    api_token: str
    scim_token: str
    xai_api_key: str
    xai_base_url: str
    xai_model: str
    free_query_limit: int
    postmark_api_token: str
    from_email: str
    reminder_scheduler_enabled: bool
    reminder_interval_seconds: int
    signwell_api_key: str
    signwell_api_base_url: str
    signwell_test_mode: bool
    signwell_webhook_token: str
    docusign_access_token: str
    docusign_integration_key: str
    docusign_user_id: str
    docusign_account_id: str
    docusign_private_key: str
    docusign_api_base_url: str
    docusign_oauth_base_url: str
    docusign_webhook_secret: str

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(__file__).resolve().parent.parent
        data_dir = Path(os.getenv("FASTCLM_DATA_DIR", str(root / "data")))
        return cls(
            root=root,
            secret=os.getenv("FASTCLM_SECRET", "fastclm-local-change-me"),
            encryption_key=os.getenv("FASTCLM_ENCRYPTION_KEY", "").strip(),
            port=int(os.getenv("FASTCLM_PORT", "5025")),
            public_url=os.getenv("FASTCLM_PUBLIC_URL", "http://localhost:5025").rstrip("/"),
            environment=os.getenv("FASTCLM_ENV_LABEL", "Local"),
            data_dir=data_dir,
            sqlite_path=Path(os.getenv("FASTCLM_DB", str(data_dir / "fastclm.sqlite"))),
            upload_dir=Path(os.getenv("FASTCLM_UPLOAD_DIR", str(data_dir / "uploads"))),
            storage_backend=os.getenv("FASTCLM_STORAGE_BACKEND", "local").strip().lower(),
            s3_bucket=os.getenv("FASTCLM_S3_BUCKET", "").strip(),
            s3_endpoint_url=os.getenv("FASTCLM_S3_ENDPOINT_URL", "").strip(),
            s3_region=os.getenv("FASTCLM_S3_REGION", "eu-west-1").strip(),
            s3_access_key_id=os.getenv("FASTCLM_S3_ACCESS_KEY_ID", "").strip(),
            s3_secret_access_key=os.getenv("FASTCLM_S3_SECRET_ACCESS_KEY", "").strip(),
            s3_prefix=os.getenv("FASTCLM_S3_PREFIX", "fastclm").strip().strip("/"),
            s3_kms_key_id=os.getenv("FASTCLM_S3_KMS_KEY_ID", "").strip(),
            clamav_host=os.getenv("FASTCLM_CLAMAV_HOST", "").strip(),
            clamav_port=int(os.getenv("FASTCLM_CLAMAV_PORT", "3310")),
            ocr_enabled=os.getenv("FASTCLM_OCR_ENABLED", "true").lower() == "true",
            ocr_language=os.getenv("FASTCLM_OCR_LANGUAGE", "eng").strip(),
            backup_key=(os.getenv("FASTCLM_BACKUP_ENCRYPTION_KEY", "") or os.getenv("FASTCLM_BACKUP_KEY", "")).strip(),
            allow_test_auth=os.getenv("FASTCLM_ALLOW_TEST_AUTH", "false").lower() == "true",
            require_email_verification=os.getenv("FASTCLM_REQUIRE_EMAIL_VERIFICATION", "false").lower() == "true",
            platform_admins=_csv("FASTCLM_PLATFORM_ADMINS"),
            google_client_id=os.getenv("GOOGLE_CLIENT_ID", "").strip(),
            google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
            google_redirect_uri=os.getenv("GOOGLE_REDIRECT_URI", "").strip(),
            google_allowed_domains=_csv("GOOGLE_ALLOWED_DOMAINS"),
            google_allowed_emails=_csv("GOOGLE_ALLOWED_EMAILS"),
            api_token=(os.getenv("FASTCLM_API_TOKEN", "") or os.getenv("FASTSME_API_TOKEN", "")).strip(),
            scim_token=os.getenv("FASTCLM_SCIM_TOKEN", "").strip(),
            xai_api_key=os.getenv("XAI_API_KEY", "").strip(),
            xai_base_url=os.getenv("XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/"),
            xai_model=os.getenv("XAI_MODEL", "grok-4-1-fast-reasoning").strip(),
            free_query_limit=max(0, int(os.getenv("FASTCLM_FREE_QUERY_LIMIT", "5"))),
            postmark_api_token=os.getenv("POSTMARK_API_TOKEN", "").strip(),
            from_email=os.getenv("FROM_EMAIL", "info@fastsme.com").strip(),
            reminder_scheduler_enabled=os.getenv("FASTCLM_REMINDER_SCHEDULER_ENABLED", "false").lower() == "true",
            reminder_interval_seconds=max(300, int(os.getenv("FASTCLM_REMINDER_INTERVAL_SECONDS", "3600"))),
            signwell_api_key=os.getenv("SIGNWELL_API_KEY", "").strip(),
            signwell_api_base_url=os.getenv("SIGNWELL_API_BASE_URL", "https://www.signwell.com/api/v1").rstrip("/"),
            signwell_test_mode=os.getenv("SIGNWELL_TEST_MODE", "true").lower() == "true",
            signwell_webhook_token=os.getenv("SIGNWELL_WEBHOOK_TOKEN", "").strip(),
            docusign_access_token=os.getenv("DOCUSIGN_ACCESS_TOKEN", "").strip(),
            docusign_integration_key=os.getenv("DOCUSIGN_INTEGRATION_KEY", "").strip(),
            docusign_user_id=os.getenv("DOCUSIGN_USER_ID", "").strip(),
            docusign_account_id=os.getenv("DOCUSIGN_ACCOUNT_ID", "").strip(),
            docusign_private_key=os.getenv("DOCUSIGN_PRIVATE_KEY", "").strip(),
            docusign_api_base_url=os.getenv("DOCUSIGN_API_BASE_URL", "https://demo.docusign.net/restapi").rstrip("/"),
            docusign_oauth_base_url=os.getenv("DOCUSIGN_OAUTH_BASE_URL", "https://account-d.docusign.com").rstrip("/"),
            docusign_webhook_secret=os.getenv("DOCUSIGN_WEBHOOK_SECRET", "").strip(),
        )


settings = Settings.from_env()
