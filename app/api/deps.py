import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, UploadFile, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User
from app.services.auth_service import AuthenticationService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(db: DbSession, token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido ou expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    subject = decode_access_token(token)
    try:
        user_id = uuid.UUID(subject)
    except (TypeError, ValueError):
        raise unauthorized from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(permission: str):
    def checker(user: CurrentUser) -> User:
        if not AuthenticationService.authorize(user, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Usuário sem permissão para esta ação")
        return user

    return checker


async def read_upload(file: UploadFile) -> bytes:
    """Lê o arquivo respeitando o limite de tamanho (RNF 3.2)."""
    max_bytes = get_settings().max_upload_size_mb * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"'{file.filename}' excede o limite de {get_settings().max_upload_size_mb} MB",
        )
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"'{file.filename}' está vazio")
    return content
