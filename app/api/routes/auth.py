from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import User
from app.schemas.api import Token, UserOut
from app.services.audit_service import register_event
from app.services.auth_service import AuthenticationService

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post(
    "/login",
    response_model=Token,
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
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha inválidos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=token)


@router.get("/me", response_model=UserOut, summary="Dados e permissões do usuário logado")
def me(user: CurrentUser):
    """Use `permissions` para decidir quais telas e botões mostrar."""
    return user
