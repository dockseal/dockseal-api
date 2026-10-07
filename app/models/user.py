import uuid

from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import IdMixin, TimestampMixin

role_permission = Table(
    "role_permission",
    Base.metadata,
    Column("role_id", ForeignKey("role.id"), primary_key=True),
    Column("permission_id", ForeignKey("permission.id"), primary_key=True),
)


class Permission(IdMixin, TimestampMixin, Base):
    __tablename__ = "permission"

    key: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")


class Role(IdMixin, TimestampMixin, Base):
    __tablename__ = "role"

    name: Mapped[str] = mapped_column(String(50), unique=True)
    permissions: Mapped[list[Permission]] = relationship(secondary=role_permission, lazy="selectin")

    def has_permission(self, key: str) -> bool:
        return any(p.key == key for p in self.permissions)


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "user"

    name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("role.id"))

    role: Mapped[Role] = relationship(lazy="joined")

    @property
    def is_active(self) -> bool:
        return self.status == "ACTIVE"

    @property
    def permissions(self) -> list[str]:
        return sorted(p.key for p in self.role.permissions)
