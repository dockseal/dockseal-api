import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agents.compliance_agent import ComplianceAnalyzer, get_analyzer
from app.api.deps import DbSession, require_permission
from app.api.uploads import extract_uploads
from app.core.config import get_settings
from app.models import (
    Container,
    Document,
    DocumentType,
    Evidence,
    EvidenceType,
    Extraction,
    Shipment,
    ShipmentContainer,
    User,
    Validation,
)
from app.models.base import new_id
from app.schemas.api import (
    ContainerIn,
    DocumentOut,
    ProcessEventOut,
    ShipmentDetail,
    ShipmentIn,
    ShipmentOut,
    ValidationOut,
)
from app.services.audit_service import list_events, register_event
from app.services.auth_service import Permissions
from app.services.extraction_service import ExtractionService
from app.services.validation_service import ValidationService

ISO_6346 = re.compile(r"^[A-Z]{4}\d{7}$")
ISO_6346_DETAIL = "Número de contêiner inválido. Use o padrão ISO 6346: 4 letras e 7 números."
CONTAINER_IN_TRANSIT_DETAIL = "Contêiner já está em trânsito em outro embarque"
DUPLICATE_SHIPMENT_ID_DETAIL = "Identificador de embarque já cadastrado"
INVALID_DOCUMENT_TYPE_DETAIL = "Tipo de documento inválido"

DOCUMENT_TYPES = {
    "BILL_OF_LADING": DocumentType.BILL_OF_LADING,
    "MANIFESTO_CARGA": DocumentType.MANIFESTO_CARGA,
    "NOTA_FISCAL": DocumentType.NOTA_FISCAL,
    "ORDEM_CARREGAMENTO": DocumentType.ORDEM_CARREGAMENTO,
    "OUTRO": DocumentType.OUTRO,
    "INVOICE": DocumentType.NOTA_FISCAL,
}
KNOWN_UPLOAD_TYPES = set(DOCUMENT_TYPES) | {"CONTAINER_PHOTO"}

router = APIRouter(prefix="/shipments", tags=["Embarques"])

Writer = Annotated[User, Depends(require_permission(Permissions.SHIPMENT_WRITE))]
Reader = Annotated[User, Depends(require_permission(Permissions.SHIPMENT_READ))]


def get_shipment_or_404(db: DbSession, shipment_id: uuid.UUID) -> Shipment:
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Embarque não encontrado")
    return shipment


def normalize_container_number(raw: str) -> str:
    number = raw.replace(" ", "").replace("-", "").upper()
    if ISO_6346.fullmatch(number) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ISO_6346_DETAIL)
    return number


def get_or_create_container(db: DbSession, data: ContainerIn) -> Container:
    number = normalize_container_number(data.container_number)
    container = db.scalar(select(Container).where(Container.container_number == number))
    if container is None:
        container = Container(**data.model_dump(exclude={"container_number"}), container_number=number)
        db.add(container)
        db.flush()
    return container


def attach_container(db: DbSession, shipment: Shipment, data: ContainerIn, *, replace_primary: bool) -> None:
    container = get_or_create_container(db, data)
    other_open = db.scalar(
        select(ShipmentContainer.id)
        .join(Shipment, Shipment.id == ShipmentContainer.shipment_id)
        .where(
            ShipmentContainer.container_id == container.id,
            ShipmentContainer.shipment_id != shipment.id,
            Shipment.returned_at.is_(None),
        )
    )
    if other_open is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=CONTAINER_IN_TRANSIT_DETAIL)

    existing = db.scalar(
        select(ShipmentContainer).where(
            ShipmentContainer.shipment_id == shipment.id,
            ShipmentContainer.container_id == container.id,
        )
    )
    if existing is None:
        link = ShipmentContainer(shipment_id=shipment.id, container_id=container.id)
        db.add(link)
        shipment.container_links.append(link)
    if shipment.container_id is None or replace_primary:
        shipment.container = container
    container.status = "IN_TRANSIT"


@router.post(
    "",
    response_model=ShipmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar embarque",
    responses={422: {"description": "Campos inválidos ou retorno previsto anterior ao despacho"}},
)
def create_shipment(db: DbSession, user: Writer, data: ShipmentIn):
    """Corpo em JSON. O contêiner é opcional e pode ser associado depois."""
    if data.dispatched_at and data.expected_return and data.expected_return < data.dispatched_at:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Retorno previsto não pode ser anterior ao despacho"
        )
    start_of_today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if data.expected_arrival is not None and data.expected_arrival < start_of_today:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Data de chegada prevista não pode ser anterior a hoje"
        )
    if data.shipment_id_custom is not None:
        taken = db.scalar(select(Shipment.id).where(Shipment.shipment_id_custom == data.shipment_id_custom))
        if taken is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=DUPLICATE_SHIPMENT_ID_DETAIL)
    shipment = Shipment(**data.model_dump(exclude={"container"}))
    db.add(shipment)
    db.flush()
    if data.container:
        attach_container(db, shipment, data.container, replace_primary=False)
    register_event(db, "SHIPMENT_CREATED", user_id=user.id, shipment_id=shipment.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=DUPLICATE_SHIPMENT_ID_DETAIL) from None
    return shipment


@router.get("", response_model=list[ShipmentOut], summary="Listar embarques")
def list_shipments(db: DbSession, _: Reader, limit: int = 50, offset: int = 0):
    """Mais recentes primeiro. Paginação por `limit` e `offset`."""
    query = select(Shipment).order_by(Shipment.created_at.desc()).limit(limit).offset(offset)
    return db.scalars(query).all()


@router.get(
    "/{shipment_id}",
    response_model=ShipmentDetail,
    summary="Detalhar embarque (com documentos)",
    responses={404: {"description": "Embarque não encontrado"}},
)
def get_shipment(db: DbSession, _: Reader, shipment_id: uuid.UUID):
    return get_shipment_or_404(db, shipment_id)


@router.put(
    "/{shipment_id}/container",
    response_model=ShipmentOut,
    summary="Associar ou trocar o contêiner",
    responses={404: {"description": "Embarque não encontrado"}},
)
def associate_container(db: DbSession, user: Writer, shipment_id: uuid.UUID, data: ContainerIn):
    shipment = get_shipment_or_404(db, shipment_id)
    attach_container(db, shipment, data, replace_primary=True)
    register_event(
        db, "CONTAINER_ASSOCIATED", user_id=user.id, shipment_id=shipment.id, observation=data.container_number
    )
    db.commit()
    return shipment


@router.post(
    "/{shipment_id}/containers",
    response_model=ShipmentOut,
    summary="Adicionar contêiner ao embarque",
    responses={
        404: {"description": "Embarque não encontrado"},
        422: {"description": "Número inválido ou contêiner em trânsito em outro embarque"},
    },
)
def add_container(db: DbSession, user: Writer, shipment_id: uuid.UUID, data: ContainerIn):
    shipment = get_shipment_or_404(db, shipment_id)
    attach_container(db, shipment, data, replace_primary=False)
    register_event(
        db, "CONTAINER_ASSOCIATED", user_id=user.id, shipment_id=shipment.id, observation=data.container_number
    )
    db.commit()
    return shipment


@router.post(
    "/{shipment_id}/documents",
    response_model=list[DocumentOut],
    status_code=status.HTTP_201_CREATED,
    summary="Enviar documentos do embarque",
    responses={
        404: {"description": "Embarque não encontrado"},
        413: {"description": "Arquivo maior que o limite (20 MB)"},
        415: {"description": "Formato de arquivo não suportado"},
        422: {"description": "Arquivo vazio/sem texto ou `types` com quantidade diferente de `files`"},
    },
)
async def upload_documents(
    db: DbSession,
    user: Annotated[User, Depends(require_permission(Permissions.DOCUMENT_UPLOAD))],
    shipment_id: uuid.UUID,
    files: Annotated[list[UploadFile], File()],
    types: Annotated[list[str] | None, Form(description="Tipo de cada arquivo, na mesma ordem")] = None,
):
    """`multipart/form-data` com `files` (um ou mais) e, opcionalmente, `types` na mesma ordem dos arquivos.

    O texto é extraído na hora e fica salvo para a validação. Pode levar alguns segundos com imagens.
    """
    shipment = get_shipment_or_404(db, shipment_id)
    if types is not None and len(types) != len(files):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Informe um tipo para cada arquivo")
    normalized = [item.strip().upper() for item in types] if types is not None else None
    if normalized is not None and any(item not in KNOWN_UPLOAD_TYPES for item in normalized):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=INVALID_DOCUMENT_TYPE_DETAIL)

    uploads = await extract_uploads(files, ExtractionService())
    folder = get_settings().upload_dir / str(shipment.id)
    folder.mkdir(parents=True, exist_ok=True)

    documents = []
    for i, upload in enumerate(uploads):
        raw_type = normalized[i] if normalized is not None else "OUTRO"
        path = folder / f"{new_id()}{Path(upload.filename).suffix.lower()}"
        path.write_bytes(upload.content)
        if raw_type == "CONTAINER_PHOTO":
            evidence = Evidence(
                type=EvidenceType.FOTO_CONTAINER,
                mime_type=files[i].content_type or "application/octet-stream",
                url=str(path),
                shipment=shipment,
            )
            evidence.extraction = Extraction(text=upload.text, processed_at=datetime.now(UTC))
            db.add(evidence)
            continue
        document = Document(
            type=DOCUMENT_TYPES[raw_type],
            filename=upload.filename,
            url=str(path),
            status="EXTRACTED",
            shipment=shipment,
        )
        document.extraction = Extraction(text=upload.text, processed_at=datetime.now(UTC))
        db.add(document)
        documents.append(document)

    register_event(
        db, "DOCUMENTS_UPLOADED", user_id=user.id, shipment_id=shipment.id, observation=f"{len(documents)} arquivo(s)"
    )
    db.commit()
    return documents


@router.post(
    "/{shipment_id}/validate",
    response_model=ValidationOut,
    summary="Validar embarque com IA",
    responses={
        404: {"description": "Embarque não encontrado"},
        422: {"description": "Embarque sem documentos"},
        502: {"description": "Falha na IA; o motivo vem em `detail`"},
    },
)
async def validate_shipment(
    db: DbSession,
    user: Annotated[User, Depends(require_permission(Permissions.ANALYSIS_RUN))],
    analyzer: Annotated[ComplianceAnalyzer, Depends(get_analyzer)],
    shipment_id: uuid.UUID,
):
    """Compara todos os documentos do embarque, salva o resultado, gera alertas (severidade MEDIA ou maior)
    e atualiza o status do embarque. Leva de 10 a 40 segundos.
    """
    shipment = get_shipment_or_404(db, shipment_id)
    try:
        return await ValidationService(db, analyzer).validate_shipment(shipment, user.id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        register_event(db, "VALIDATION", status="FAILURE", user_id=user.id, shipment_id=shipment_id)
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"Falha ao analisar os documentos com a IA: {exc}") from exc


@router.get(
    "/{shipment_id}/validations",
    response_model=list[ValidationOut],
    summary="Histórico de validações do embarque",
    responses={404: {"description": "Embarque não encontrado"}},
)
def list_validations(db: DbSession, _: Reader, shipment_id: uuid.UUID):
    get_shipment_or_404(db, shipment_id)
    query = select(Validation).where(Validation.shipment_id == shipment_id).order_by(Validation.created_at.desc())
    return db.scalars(query).all()


@router.get(
    "/{shipment_id}/events",
    response_model=list[ProcessEventOut],
    summary="Histórico operacional do embarque",
    responses={404: {"description": "Embarque não encontrado"}},
)
def list_shipment_events(
    db: DbSession,
    _: Annotated[User, Depends(require_permission(Permissions.HISTORY_READ))],
    shipment_id: uuid.UUID,
    limit: int = 100,
):
    get_shipment_or_404(db, shipment_id)
    return list_events(db, shipment_id=shipment_id, limit=limit)
