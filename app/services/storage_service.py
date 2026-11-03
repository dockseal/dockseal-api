import re
from pathlib import Path

from app.core.config import get_settings

_client = None


def storage_backend() -> str:
    s = get_settings()
    if s.r2_account_id and s.r2_access_key_id and s.r2_secret_access_key and s.r2_bucket:
        return "r2"
    return "local"


def _safe_key(key: str) -> str:
    parts = [p for p in key.replace("\\", "/").split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        raise ValueError("Chave de arquivo invalida")
    return "/".join(re.sub(r"[^\w.\- ]", "_", p) for p in parts)


def _r2():
    global _client
    if _client is None:
        import boto3

        s = get_settings()
        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{s.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=s.r2_access_key_id,
            aws_secret_access_key=s.r2_secret_access_key,
            region_name="auto",
        )
    return _client


def _local_path(key: str) -> Path:
    base = Path(get_settings().upload_dir).resolve()
    path = (base / key).resolve()
    if path != base and base not in path.parents:
        raise ValueError("Chave de arquivo invalida")
    return path


def save_file(key: str, data: bytes, content_type: str | None = None) -> str:
    """Grava no R2 (ou no disco local, sem as variaveis R2_*) e devolve a chave."""
    key = _safe_key(key)
    if storage_backend() == "r2":
        extra = {"ContentType": content_type} if content_type else {}
        _r2().put_object(Bucket=get_settings().r2_bucket, Key=key, Body=data, **extra)
    else:
        path = _local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return key


def read_file(key: str) -> bytes:
    key = _safe_key(key)
    if storage_backend() == "r2":
        return _r2().get_object(Bucket=get_settings().r2_bucket, Key=key)["Body"].read()
    return _local_path(key).read_bytes()


def delete_file(key: str) -> None:
    key = _safe_key(key)
    if storage_backend() == "r2":
        _r2().delete_object(Bucket=get_settings().r2_bucket, Key=key)
    else:
        _local_path(key).unlink(missing_ok=True)