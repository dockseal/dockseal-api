import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import User
from app.core.security import create_access_token, create_refresh_token, decode_refresh_token
from app.schemas.api import LoginResponse, LoginUser, RefreshIn, Token, UserOut
from app.services.audit_service import register_event
from app.services.auth_service import AuthenticationService

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Fazer login",
    responses={401: {"description": "E-mail ou senha inválidos"}},
)
def login(db: DbSession, form: Annotated[OAuth2PasswordRequestForm, Depends()]):
    """Envie como **formulário** (`application/x-www-form-urlencoded`), não JSON.

    - `username`: e-mail do usuário
    - `password`: senha

    O token expira em 60 minutos (padrão). Quando qualquer rota responder 401, faça login de novo.
    """
    token = AuthenticationService(db).authenticate(form.username, form.password)
    user = db.scalar(select(User).where(User.email == form.username.lower()))
    register_event(
        db,
        "LOGIN",
        status="SUCCESS" if token else "FAILURE",
        user_id=user.id if user else None,
    )
    db.commit()
    if token is None or user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha inválidos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return LoginResponse(
        access_token=token,
        refresh_token=create_refresh_token(str(user.id)),
        user=LoginUser(id=user.id, name=user.name, role=user.role.name),
    )


@router.post(
    "/refresh",
    response_model=Token,
    summary="Renovar o token de acesso",
    responses={401: {"description": "Refresh token inválido"}},
)
def refresh_token(db: DbSession, data: RefreshIn):
    """Corpo JSON: `{ "refresh_token": "..." }`. Não invalida o refresh token anterior."""
    subject = decode_refresh_token(data.refresh_token)
    user = None
    if subject is not None:
        try:
            user = db.get(User, uuid.UUID(subject))
        except ValueError:
            user = None
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido")
    user_id = str(user.id)
    return Token(access_token=create_access_token(user_id), refresh_token=create_refresh_token(user_id))


@router.get("/me", response_model=UserOut, summary="Dados e permissões do usuário logado")
def me(user: CurrentUser):
    """Use `permissions` para decidir quais telas e botões mostrar."""
    return user
