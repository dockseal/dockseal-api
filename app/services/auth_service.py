from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.models import Permission, Role, User


class Permissions:
    SHIPMENT_WRITE = "shipment:write"
    SHIPMENT_READ = "shipment:read"
    DOCUMENT_UPLOAD = "document:upload"
    ANALYSIS_RUN = "analysis:run"
    ALERT_READ = "alert:read"
    ALERT_MANAGE = "alert:manage"
    HISTORY_READ = "history:read"


PERMISSION_DESCRIPTIONS = {
    Permissions.SHIPMENT_WRITE: "Registrar embarques e associar contêineres",
    Permissions.SHIPMENT_READ: "Consultar embarques",
    Permissions.DOCUMENT_UPLOAD: "Enviar documentos e evidências",
    Permissions.ANALYSIS_RUN: "Executar análise de conformidade com IA",
    Permissions.ALERT_READ: "Consultar alertas",
    Permissions.ALERT_MANAGE: "Resolver ou fechar alertas",
    Permissions.HISTORY_READ: "Consultar histórico operacional",
}

ROLE_PERMISSIONS = {
    "OPERADOR": [
        Permissions.SHIPMENT_WRITE,
        Permissions.SHIPMENT_READ,
        Permissions.DOCUMENT_UPLOAD,
        Permissions.ANALYSIS_RUN,
        Permissions.ALERT_READ,
    ],
    "GESTOR": [
        Permissions.SHIPMENT_READ,
        Permissions.ANALYSIS_RUN,
        Permissions.ALERT_READ,
        Permissions.ALERT_MANAGE,
        Permissions.HISTORY_READ,
    ],
    "ADMIN": list(PERMISSION_DESCRIPTIONS),
}


class AuthenticationService:
    def __init__(self, db: Session):
        self.db = db

    def authenticate(self, email: str, password: str) -> str | None:
        """Retorna o token JWT se as credenciais forem válidas."""
        user = self.db.scalar(select(User).where(User.email == email.lower()))
        if user is None or not user.is_active or not verify_password(password, user.password):
            return None
        return create_access_token(user.id)

    @staticmethod
    def authorize(user: User, permission: str) -> bool:
        return user.role.has_permission(permission)

    def create_user(self, name: str, email: str, password: str, role_name: str) -> User:
        role = self.db.scalar(select(Role).where(Role.name == role_name))
        if role is None:
            raise ValueError(f"Perfil inexistente: {role_name}")
        user = User(name=name, email=email.lower(), password=hash_password(password), role=role)
        self.db.add(user)
        self.db.commit()
        return user


def seed_roles(db: Session) -> None:
    """Garante que perfis e permissões padrão existam (idempotente)."""
    permissions = {p.key: p for p in db.scalars(select(Permission))}
    for key, description in PERMISSION_DESCRIPTIONS.items():
        if key not in permissions:
            permissions[key] = Permission(key=key, description=description)
            db.add(permissions[key])

    roles = {r.name: r for r in db.scalars(select(Role))}
    for name, keys in ROLE_PERMISSIONS.items():
        role = roles.get(name) or Role(name=name)
        role.permissions = [permissions[k] for k in keys]
        db.add(role)
    db.commit()
