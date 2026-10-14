import re
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

password_hash = PasswordHash.recommended()

_PASSWORD_MESSAGE = (
    "Senha deve ter no mínimo 8 caracteres, com maiúscula, minúscula, número e caractere especial."
)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def validate_new_password(password: str) -> None:
    if (
        len(password) < 8
        or re.search(r"[A-Z]", password) is None
        or re.search(r"[a-z]", password) is None
        or re.search(r"\d", password) is None
        or re.search(r"[^A-Za-z0-9]", password) is None
    ):
        raise ValueError(_PASSWORD_MESSAGE)


def create_access_token(subject: str) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire, "typ": "access"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    payload = {"sub": subject, "exp": expire, "typ": "refresh"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode(token: str) -> dict | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    return payload


def decode_access_token(token: str) -> str | None:
    payload = _decode(token)
    if payload is None or payload.get("typ") == "refresh":
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None


def decode_refresh_token(token: str) -> str | None:
    payload = _decode(token)
    if payload is None or payload.get("typ") != "refresh":
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None
