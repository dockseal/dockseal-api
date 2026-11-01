import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select, update

from app.api.deps import DbSession, require_permission
from app.core.security import hash_password, validate_new_password
from app.models import ProcessEvent, Role, User
from app.schemas.api import UserCreateIn, UserOut, UserUpdateIn
from app.services.audit_service import register_event
from app.services.auth_service import Permissions

router = APIRouter(tags=["Usuários"])


def _validate_password(password: str) -> None:
    try:
        validate_new_password(password)
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


def _role(db: DbSession, name: str) -> Role:
    role = db.scalar(select(Role).where(Role.name == name))
    if role is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Perfil inexistente.")
    return role


def _email_taken(db: DbSession, email: str, user_id: uuid.UUID | None = None) -> bool:
    existing = db.scalar(select(User).where(User.email == email))
    return existing is not None and existing.id != user_id


def _is_last_active_admin(db: DbSession, user: User) -> bool:
    if user.role.name != "ADMIN" or user.status != "ACTIVE":
        return False
    count = db.scalar(
        select(func.count()).select_from(User).join(Role).where(Role.name == "ADMIN", User.status == "ACTIVE")
    )
    return count == 1


def _get_user(db: DbSession, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")
    return user


@router.get("/users", response_model=list[UserOut], summary="Listar usuários")
def list_users(
    db: DbSession,
    _: Annotated[User, Depends(require_permission(Permissions.USER_MANAGE))],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return db.scalars(select(User).order_by(User.name, User.email).limit(limit).offset(offset)).all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED, summary="Criar usuário")
def create_user(
    db: DbSession,
    actor: Annotated[User, Depends(require_permission(Permissions.USER_MANAGE))],
    data: UserCreateIn,
):
    _validate_password(data.password)
    if _email_taken(db, data.email):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="E-mail já cadastrado")
    user = User(
        name=data.name,
        email=data.email,
        password_hash=hash_password(data.password),
        status="ACTIVE",
        role=_role(db, data.role),
    )
    db.add(user)
    db.flush()
    register_event(
        db,
        "USER_CREATED",
        user_id=actor.id,
        observation=f"Usuário {user.email} criado com o perfil {data.role}.",
    )
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut, summary="Atualizar usuário")
def update_user(
    db: DbSession,
    actor: Annotated[User, Depends(require_permission(Permissions.USER_MANAGE))],
    user_id: uuid.UUID,
    data: UserUpdateIn,
):
    user = _get_user(db, user_id)
    if _is_last_active_admin(db, user) and data.role is not None and data.role != "ADMIN":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Não é possível alterar o perfil do último administrador.",
        )
    if _is_last_active_admin(db, user) and data.status == "INACTIVE":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Não é possível desativar o último administrador.",
        )
    if data.email is not None:
        if _email_taken(db, data.email, user.id):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="E-mail já cadastrado")
        user.email = data.email
    if data.name is not None:
        user.name = data.name
    if data.role is not None:
        user.role = _role(db, data.role)
    if data.status is not None:
        user.status = data.status
    password = data.password.strip() if data.password else ""
    if password:
        _validate_password(password)
        user.password_hash = hash_password(password)
    register_event(db, "USER_UPDATED", user_id=actor.id, observation=f"Usuário {user.email} atualizado.")
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Excluir usuário")
def delete_user(
    db: DbSession,
    actor: Annotated[User, Depends(require_permission(Permissions.USER_MANAGE))],
    user_id: uuid.UUID,
):
    user = _get_user(db, user_id)
    if user.id == actor.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Você não pode excluir o próprio usuário.")
    if _is_last_active_admin(db, user):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Não é possível excluir o último administrador.",
        )
    email = user.email
    register_event(db, "USER_DELETED", user_id=actor.id, observation=f"Usuário {email} excluído.")
    db.execute(update(ProcessEvent).where(ProcessEvent.user_id == user.id).values(user_id=None))
    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
