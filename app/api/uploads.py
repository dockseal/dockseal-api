from dataclasses import dataclass

from fastapi import HTTPException, UploadFile, status

from app.api.deps import read_upload
from app.core.config import get_settings
from app.services.extraction_service import ExtractionError, ExtractionService


@dataclass
class ExtractedUpload:
    filename: str
    content: bytes
    text: str


async def extract_uploads(files: list[UploadFile], extractor: ExtractionService) -> list[ExtractedUpload]:
    settings = get_settings()
    if not files:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Envie ao menos um arquivo")
    if len(files) > settings.max_files_per_analysis:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Envie no máximo {settings.max_files_per_analysis} arquivos por vez",
        )

    extracted = []
    for file in files:
        filename = file.filename or "documento"
        if not extractor.is_supported(filename):
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=f"Formato de '{filename}' não é suportado"
            )
        content = await read_upload(file)
        try:
            text = await extractor.extract_text(filename, content)
        except ExtractionError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"{filename}: {exc}") from exc
        if not text.strip():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Nenhum texto encontrado em '{filename}'"
            )
        extracted.append(ExtractedUpload(filename=filename, content=content, text=text))
    return extracted
