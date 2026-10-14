import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from app.models import DocumentType, EvidenceType
from app.schemas.analysis import AnalysisResult


def _as_utc(value: datetime) -> datetime:
    # O SQLite não guarda fuso: datas sem fuso são tratadas como UTC para a API sempre responder com "Z".
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]

ShipmentStatus = Literal["REGISTERED", "VALIDATED", "PENDING_REVIEW"]
AlertStatus = Literal["OPEN", "RESOLVED", "CLOSED", "DISMISSED"]
AlertSeverity = Literal["BAIXA", "MEDIA", "ALTA", "CRITICA"]
ValidationStatus = Literal["CONFORME", "DIVERGENTE", "INCONCLUSIVO"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str = Field(description="JWT. Envie em `Authorization: Bearer <token>`")
    token_type: str = "bearer"
    refresh_token: str


class LoginUser(BaseModel):
    id: uuid.UUID
    name: str
    role: Literal["OPERADOR", "GESTOR", "ADMIN"]


class LoginResponse(Token):
    user: LoginUser


class RefreshIn(BaseModel):
    refresh_token: str


class RoleOut(ORMModel):
    name: Literal["OPERADOR", "GESTOR", "ADMIN"]


class UserOut(ORMModel):
    id: uuid.UUID
    name: str
    email: str
    status: str
    role: RoleOut
    permissions: list[str] = Field(
        description="Permissões do usuário. Use para mostrar/esconder telas e botões no front-end"
    )


class ContainerIn(BaseModel):
    container_number: str = Field(
        min_length=4, max_length=20, description="Espaços e hífens são removidos", examples=["MSCU 123456-7"]
    )
    iso_code: str | None = Field(default=None, examples=["22G1"])
    type: str | None = Field(default=None, examples=["Dry 20'"])
    owner: str | None = Field(default=None, examples=["MSC"])


class ContainerOut(ORMModel):
    id: uuid.UUID
    container_number: str
    iso_code: str | None
    type: str | None
    owner: str | None
    status: str


class ShipmentIn(BaseModel):
    origin: str = Field(min_length=1, examples=["Santos"])
    destination: str = Field(min_length=1, examples=["Roterdã"])
    shipment_id_custom: str | None = Field(default=None, min_length=1, max_length=50)
    transport_company: str | None = Field(default=None, min_length=1, max_length=150)
    dispatched_at: UtcDatetime | None = Field(default=None, examples=["2026-10-03T10:00:00Z"])
    expected_arrival: UtcDatetime | None = Field(default=None, examples=["2026-10-12T14:00:00Z"])
    expected_return: UtcDatetime | None = Field(
        default=None, description="Não pode ser anterior a dispatched_at", examples=["2026-11-03T10:00:00Z"]
    )
    container: ContainerIn | None = None

    @field_validator("shipment_id_custom", mode="before")
    @classmethod
    def blank_custom_id_is_null(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("transport_company", mode="before")
    @classmethod
    def strip_transport_company(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class DocumentOut(ORMModel):
    id: uuid.UUID
    type: DocumentType
    filename: str
    status: str
    created_at: UtcDatetime


class ShipmentOut(ORMModel):
    id: uuid.UUID
    origin: str
    destination: str
    shipment_id_custom: str | None
    transport_company: str | None
    dispatched_at: UtcDatetime | None
    expected_arrival: UtcDatetime | None
    expected_return: UtcDatetime | None
    returned_at: UtcDatetime | None
    status: ShipmentStatus = Field(
        description="REGISTERED (cadastrado), VALIDATED (validado sem divergências), "
        "PENDING_REVIEW (validado com divergências ou inconclusivo)"
    )
    container: ContainerOut | None
    containers: list[ContainerOut]
    created_at: UtcDatetime


class EvidenceOut(ORMModel):
    id: uuid.UUID
    type: EvidenceType
    mime_type: str
    url: str
    location: str | None
    created_at: UtcDatetime


class ShipmentDetail(ShipmentOut):
    documents: list[DocumentOut]
    evidences: list[EvidenceOut]


class ValidationOut(ORMModel):
    id: uuid.UUID
    status: ValidationStatus
    details: str = Field(description="Resumo da análise (igual a result.summary)")
    confidence_score: float | None
    shipment_id: uuid.UUID | None
    result: AnalysisResult
    created_at: UtcDatetime


class AlertOut(ORMModel):
    id: uuid.UUID
    severity: AlertSeverity
    description: str
    status: AlertStatus
    resolution_note: str | None
    shipment_id: uuid.UUID | None
    validation_id: uuid.UUID | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class AlertStatusIn(BaseModel):
    status: AlertStatus
    resolution_note: str | None = Field(default=None, max_length=2000)


class ProcessEventOut(ORMModel):
    id: uuid.UUID
    step: str = Field(description="Ação registrada, ex.: LOGIN, SHIPMENT_CREATED, DOCUMENTS_UPLOADED, VALIDATION")
    status: str = Field(description="SUCCESS, FAILURE ou o status da análise")
    observation: str | None
    user_id: uuid.UUID | None
    shipment_id: uuid.UUID | None
    created_at: UtcDatetime


class VolumeTrendPoint(BaseModel):
    date: str
    count: int


class DashboardMetrics(BaseModel):
    shipments_in_yard: int
    average_transit_hours: float | None
    efficiency_percent: float | None
    volume_trend: list[VolumeTrendPoint]
