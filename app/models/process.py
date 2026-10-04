from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import IdMixin, TimestampMixin


class ProcessEvent(IdMixin, TimestampMixin, Base):
    """Trilha de auditoria: cada ação relevante do sistema gera um evento."""

    __tablename__ = "process_event"

    step: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30))
    observation: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("user.id"))
    shipment_id: Mapped[str | None] = mapped_column(ForeignKey("shipment.id"))


class Job(IdMixin, TimestampMixin, Base):
    __tablename__ = "job"

    type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    priority: Mapped[str] = mapped_column(String(20), default="NORMAL")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[str] = mapped_column(Text, default="{}")
