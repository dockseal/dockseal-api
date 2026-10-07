import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from app.agents.compliance_agent import ComplianceAnalyzer, get_analyzer
from app.api.deps import DbSession, require_permission
from app.api.uploads import extract_uploads
from app.core.config import get_settings
from app.models import Container, Document, DocumentType, Extraction, Shipment, User, Validation
from app.models.base import new_id
from app.schemas.api import ContainerIn, DocumentOut, ShipmentDetail, ShipmentIn, ShipmentOut, ValidationOut
from app.services.audit_service import register_event
from app.services.auth_service import Permissions
from app.services.extraction_service import ExtractionService
from app.services.validation_service import ValidationService

router = APIRouter(prefix="/shipments", tags=["Embarques"])

Writer = Annotated[User, Depends(require_permission(Permissions.SHIPMENT_WRITE))]
Reader = Annotated[User, Depends(require_permission(Permissions.SHIPMENT_READ))]


def get_shipment_or_404(db: DbSession, shipment_id: uuid.UUID) -> Shipment:
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Embarque não encontrado")
    return shipment


def get_or_create_container(db: DbSession, data: ContainerIn) -> Container:
    number = data.container_number.replace(" ", "").replace("-", "").upper()
    container = db.scalar(select(Container).where(Container.container_number == number))
    if container is None:
        container = Container(**data.model_dump(exclude={"container_number"}), container_number=number)
        db.add(container)
    return container


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
    shipment = Shipment(**data.model_dump(exclude={"container"}))
    if data.container:
        shipment.container = get_or_create_container(db, data.container)
    db.add(shipment)
    db.flush()
    register_event(db, "SHIPMENT_CREATED", user_id=user.id, shipment_id=shipment.id)
    db.commit()
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
    shipment.container = get_or_create_container(db, data)
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
    types: Annotated[list[DocumentType] | None, Form(description="Tipo de cada arquivo, na mesma ordem")] = None,
):
    """`multipart/form-data` com `files` (um ou mais) e, opcionalmente, `types` na mesma ordem dos arquivos.

    O texto é extraído na hora e fica salvo para a validação. Pode levar alguns segundos com imagens.
    """
    shipment = get_shipment_or_404(db, shipment_id)
    if types and len(types) != len(files):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Informe um tipo para cada arquivo")

    uploads = await extract_uploads(files, ExtractionService())
    folder = get_settings().upload_dir / str(shipment.id)
    folder.mkdir(parents=True, exist_ok=True)

    documents = []
    for i, upload in enumerate(uploads):
        path = folder / f"{new_id()}{Path(upload.filename).suffix.lower()}"
        path.write_bytes(upload.content)
        document = Document(
            type=types[i] if types else DocumentType.OUTRO,
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
