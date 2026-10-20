import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import IdMixin, TimestampMixin


class DocumentType(StrEnum):
    BILL_OF_LADING = "BILL_OF_LADING"
    MANIFESTO_CARGA = "MANIFESTO_CARGA"
    NOTA_FISCAL = "NOTA_FISCAL"
    ORDEM_CARREGAMENTO = "ORDEM_CARREGAMENTO"
    OUTRO = "OUTRO"


class EvidenceType(StrEnum):
    FOTO_CONTAINER = "FOTO_CONTAINER"
    FOTO_DOCUMENTO = "FOTO_DOCUMENTO"
    ARQUIVO_DIGITAL = "ARQUIVO_DIGITAL"
    COMPROVANTE = "COMPROVANTE"
    OUTRO = "OUTRO"


class Container(IdMixin, TimestampMixin, Base):
    __tablename__ = "container"

    container_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    iso_code: Mapped[str | None] = mapped_column(String(10))
    type: Mapped[str | None] = mapped_column(String(50))
    owner: Mapped[str | None] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(30), default="AVAILABLE")

    shipments: Mapped[list["Shipment"]] = relationship(back_populates="container")


class ShipmentContainer(IdMixin, TimestampMixin, Base):
    __tablename__ = "shipment_container"
    __table_args__ = (UniqueConstraint("shipment_id", "container_id", name="uq_shipment_container"),)

    shipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shipment.id"))
    container_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("container.id"))

    shipment: Mapped["Shipment"] = relationship(back_populates="container_links")
    container: Mapped[Container] = relationship(lazy="joined")


class Shipment(IdMixin, TimestampMixin, Base):
    __tablename__ = "shipment"

    origin: Mapped[str] = mapped_column(String(150))
    destination: Mapped[str] = mapped_column(String(150))
    shipment_id_custom: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    transport_company: Mapped[str | None] = mapped_column(String(150))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_arrival: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_return: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="REGISTERED")
    container_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("container.id"))

    container: Mapped[Container | None] = relationship(back_populates="shipments", lazy="joined")
    container_links: Mapped[list[ShipmentContainer]] = relationship(
        back_populates="shipment",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ShipmentContainer.created_at",
    )
    documents: Mapped[list["Document"]] = relationship(back_populates="shipment", cascade="all, delete-orphan")
    evidences: Mapped[list["Evidence"]] = relationship(back_populates="shipment", cascade="all, delete-orphan")

    @property
    def containers(self) -> list[Container]:
        return [link.container for link in self.container_links]


class Document(IdMixin, TimestampMixin, Base):
    __tablename__ = "document"

    type: Mapped[DocumentType] = mapped_column(Enum(DocumentType), default=DocumentType.OUTRO)
    document_number: Mapped[str | None] = mapped_column(String(100))
    issue_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issuer: Mapped[str | None] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(30), default="UPLOADED")
    filename: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(500))
    shipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shipment.id"))

    shipment: Mapped[Shipment] = relationship(back_populates="documents")
    extraction: Mapped["Extraction | None"] = relationship(back_populates="document", uselist=False)


class Evidence(IdMixin, TimestampMixin, Base):
    __tablename__ = "evidence"

    type: Mapped[EvidenceType] = mapped_column(Enum(EvidenceType), default=EvidenceType.OUTRO)
    mime_type: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(150))
    shipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shipment.id"))

    shipment: Mapped[Shipment] = relationship(back_populates="evidences")
    extraction: Mapped["Extraction | None"] = relationship(back_populates="evidence", uselist=False)


class Extraction(IdMixin, TimestampMixin, Base):
    """Texto extraído (OCR/parser) de uma evidência ou de um documento."""

    __tablename__ = "extraction"

    text: Mapped[str] = mapped_column(Text)
    confidence_score: Mapped[float | None]
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence.id"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document.id"))

    document: Mapped[Document | None] = relationship(back_populates="extraction")
    evidence: Mapped[Evidence | None] = relationship(back_populates="extraction")
