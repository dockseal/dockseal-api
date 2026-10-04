from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import IdMixin, TimestampMixin


class Validation(IdMixin, TimestampMixin, Base):
    __tablename__ = "validation"

    type: Mapped[str] = mapped_column(String(50), default="CROSS_DOCUMENT")
    status: Mapped[str] = mapped_column(String(30))
    details: Mapped[str] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSON)
    confidence_score: Mapped[float | None]
    extraction_id: Mapped[str | None] = mapped_column(ForeignKey("extraction.id"))
    shipment_id: Mapped[str | None] = mapped_column(ForeignKey("shipment.id"))

    alerts: Mapped[list["Alert"]] = relationship(back_populates="validation")


class Alert(IdMixin, TimestampMixin, Base):
    __tablename__ = "alert"

    severity: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    shipment_id: Mapped[str | None] = mapped_column(ForeignKey("shipment.id"))
    validation_id: Mapped[str | None] = mapped_column(ForeignKey("validation.id"))

    validation: Mapped[Validation | None] = relationship(back_populates="alerts")

    def open(self) -> None:
        self.status = "OPEN"

    def resolve(self) -> None:
        self.status = "RESOLVED"

    def close(self) -> None:
        self.status = "CLOSED"
