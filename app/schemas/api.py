from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models import DocumentType
from app.schemas.analysis import AnalysisResult


def _as_utc(value: datetime) -> datetime:
    # O SQLite não guarda fuso: datas sem fuso são tratadas como UTC para a API sempre responder com "Z".
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]

ShipmentStatus = Literal["REGISTERED", "VALIDATED", "PENDING_REVIEW"]
AlertStatus = Literal["OPEN", "RESOLVED", "CLOSED"]
AlertSeverity = Literal["BAIXA", "MEDIA", "ALTA", "CRITICA"]
ValidationStatus = Literal["CONFORME", "DIVERGENTE", "INCONCLUSIVO"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str = Field(description="JWT. Envie em `Authorization: Bearer <token>`")
    token_type: str = "bearer"


class RoleOut(ORMModel):
    name: Literal["OPERADOR", "GESTOR", "ADMIN"]


class UserOut(ORMModel):
    id: str
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
    id: str
    container_number: str
    iso_code: str | None
    type: str | None
    owner: str | None
    status: str


class ShipmentIn(BaseModel):
    origin: str = Field(min_length=1, examples=["Santos"])
    destination: str = Field(min_length=1, examples=["Roterdã"])
    dispatched_at: UtcDatetime | None = Field(default=None, examples=["2026-10-03T10:00:00Z"])
    expected_return: UtcDatetime | None = Field(
        default=None, description="Não pode ser anterior a dispatched_at", examples=["2026-11-03T10:00:00Z"]
    )
    container: ContainerIn | None = None


class DocumentOut(ORMModel):
    id: str
    type: DocumentType
    filename: str
    status: str
    created_at: UtcDatetime


class ShipmentOut(ORMModel):
    id: str
    origin: str
    destination: str
    dispatched_at: UtcDatetime | None
    expected_return: UtcDatetime | None
    returned_at: UtcDatetime | None
    status: ShipmentStatus = Field(
        description="REGISTERED (cadastrado), VALIDATED (validado sem divergências), "
        "PENDING_REVIEW (validado com divergências ou inconclusivo)"
    )
    container: ContainerOut | None
    created_at: UtcDatetime


class ShipmentDetail(ShipmentOut):
    documents: list[DocumentOut]


class ValidationOut(ORMModel):
    id: str
    status: ValidationStatus
    details: str = Field(description="Resumo da análise (igual a result.summary)")
    confidence_score: float | None
    shipment_id: str | None
    result: AnalysisResult
    created_at: UtcDatetime


class AlertOut(ORMModel):
    id: str
    severity: AlertSeverity
    description: str
    status: AlertStatus
    shipment_id: str | None
    validation_id: str | None
    created_at: UtcDatetime


class AlertStatusIn(BaseModel):
    status: AlertStatus


class ProcessEventOut(ORMModel):
    id: str
    step: str = Field(description="Ação registrada, ex.: LOGIN, SHIPMENT_CREATED, DOCUMENTS_UPLOADED, VALIDATION")
    status: str = Field(description="SUCCESS, FAILURE ou o status da análise")
    observation: str | None
    user_id: str | None
    shipment_id: str | None
    created_at: UtcDatetime
