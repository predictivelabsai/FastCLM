"""Private source-object storage with local and S3-compatible backends."""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile

from fastclm.config import Settings, settings


def safe_object_key(value: str) -> str:
    key = PurePosixPath(value)
    if key.is_absolute() or not value or ".." in key.parts or "\\" in value:
        raise ValueError("Invalid storage object key")
    return str(key)


class LocalStorage:
    name = "local"

    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        safe = safe_object_key(key)
        path = (self.root / safe).resolve()
        root = self.root.resolve()
        if root not in path.parents:
            raise ValueError("Invalid storage object key")
        return path

    def put(self, key: str, content: bytes, media_type: str = "application/octet-stream") -> None:
        del media_type
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.replace(target)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes()

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()


class S3Storage:
    name = "s3"

    def __init__(self, config: Settings):
        if not config.s3_bucket:
            raise RuntimeError("FASTCLM_S3_BUCKET is required for S3 storage")
        import boto3

        kwargs = {
            "region_name": config.s3_region,
            "endpoint_url": config.s3_endpoint_url or None,
        }
        if config.s3_access_key_id:
            kwargs.update(
                aws_access_key_id=config.s3_access_key_id,
                aws_secret_access_key=config.s3_secret_access_key,
            )
        self.client = boto3.client("s3", **kwargs)
        self.bucket = config.s3_bucket
        self.prefix = config.s3_prefix
        self.kms_key_id = config.s3_kms_key_id

    def _key(self, key: str) -> str:
        safe = safe_object_key(key)
        return f"{self.prefix}/{safe}" if self.prefix else safe

    def put(self, key: str, content: bytes, media_type: str = "application/octet-stream") -> None:
        encryption = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self.kms_key_id} if self.kms_key_id else {"ServerSideEncryption": "AES256"}
        self.client.put_object(Bucket=self.bucket, Key=self._key(key), Body=content, ContentType=media_type, **encryption)

    def get(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=self._key(key))["Body"].read()
        except self.client.exceptions.NoSuchKey as exc:
            raise FileNotFoundError(key) from exc

    def delete(self, key: str) -> bool:
        existed = self.exists(key)
        if existed:
            self.client.delete_object(Bucket=self.bucket, Key=self._key(key))
        return existed

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except Exception as exc:
            response = getattr(exc, "response", {})
            if str(response.get("Error", {}).get("Code", "")) in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise


def get_storage(backend: str | None = None, config: Settings | None = None):
    config = config or settings
    selected = (backend or config.storage_backend).lower()
    if selected == "local":
        return LocalStorage(config.upload_dir)
    if selected == "s3":
        return S3Storage(config)
    raise ValueError(f"Unsupported storage backend: {selected}")
