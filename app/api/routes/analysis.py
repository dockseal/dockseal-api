from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.agents.compliance_agent import ComplianceAnalyzer, get_analyzer
from app.api.deps import DbSession, require_permission
from app.api.uploads import extract_uploads
from app.models import User
from app.schemas.analysis import AnalysisResult, SourceDocument
from app.services.audit_service import register_event
from app.services.auth_service import Permissions
from app.services.extraction_service import ExtractionService
from app.services.validation_service import ValidationService

router = APIRouter(prefix="/analysis", tags=["Análise de documentos"])


@router.post(
    "",
    response_model=AnalysisResult,
    summary="Analisar documentos avulsos com IA",
    responses={
        413: {"description": "Arquivo maior que o limite (20 MB)"},
        415: {"description": "Formato de arquivo não suportado"},
        422: {"description": "Nenhum arquivo, arquivo vazio/sem texto ou mais de 10 arquivos"},
        502: {"description": "Falha na IA; o motivo vem em `detail`"},
    },
)
async def analyze_documents(
    db: DbSession,
    user: Annotated[User, Depends(require_permission(Permissions.ANALYSIS_RUN))],
    analyzer: Annotated[ComplianceAnalyzer, Depends(get_analyzer)],
    files: Annotated[list[UploadFile], File(description="Um ou mais documentos (PDF, DOCX, TXT ou imagem)")],
):
    """Envie de 1 a 10 arquivos em `multipart/form-data`, todos no campo `files`.

    Formatos: PDF, DOCX, TXT, CSV, MD, XML, JSON, PNG, JPG, WEBP. Não precisa de embarque cadastrado.
    A resposta leva de 10 a 40 segundos: mostre um indicador de carregamento.
    """
    uploads = await extract_uploads(files, ExtractionService())
    documents = [SourceDocument(name=u.filename, text=u.text) for u in uploads]

    service = ValidationService(db, analyzer)
    try:
        result = await service.compare_documents(documents)
    except Exception as exc:
        register_event(db, "ANALYSIS", status="FAILURE", user_id=user.id, observation=str(exc)[:500])
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"Falha ao analisar os documentos com a IA: {exc}") from exc

    service.save_validation(result)
    register_event(
        db,
        "ANALYSIS",
        status=result.status.value,
        user_id=user.id,
        observation=f"{len(documents)} documento(s), {len(result.divergences)} divergência(s)",
    )
    db.commit()
    return result
