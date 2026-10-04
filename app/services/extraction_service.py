import base64
import io
from pathlib import Path

import pypdfium2 as pdfium
from docx import Document as DocxDocument
from PIL import Image, ImageOps
from pypdf import PdfReader

from app.core.config import get_settings

TEXT_EXTENSIONS = {".txt", ".csv", ".md", ".xml", ".json"}
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | set(IMAGE_MIME) | {".pdf", ".docx"}

OCR_PROMPT = (
    "Cada página do documento foi dividida em faixas horizontais consecutivas, de cima para baixo, com "
    "pequena sobreposição: junte as faixas e não repita linhas duplicadas pela sobreposição. "
    "Transcreva todo o texto exatamente como aparece, preservando números, "
    "códigos, unidades e a estrutura de tabelas (use Markdown). Não resuma, não corrija e não "
    "interprete. Nunca adivinhe: se um caractere ou palavra estiver duvidoso (ex.: manuscrito), "
    "escreva a melhor leitura seguida de [?]; se estiver ilegível, escreva [ilegível]. "
    "Responda apenas com a transcrição."
)

# Abaixo disso consideramos que o PDF é digitalizado (imagem) e precisa de OCR.
MIN_PDF_TEXT_CHARS = 50
OCR_DPI = 300
# Faixa com altura = 55% da largura e 15% de sobreposição com a próxima.
STRIP_ASPECT = 0.55
STRIP_OVERLAP = 0.15
MAX_OCR_PAGES = 10


class ExtractionError(Exception):
    pass


class ExtractionService:
    """Converte arquivos em texto. PDFs/DOCX com texto são lidos localmente; imagens e PDFs digitalizados vão para o OCR."""

    def is_supported(self, filename: str) -> bool:
        return Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS

    async def extract_text(self, filename: str, content: bytes) -> str:
        ext = Path(filename).suffix.lower()

        if ext in TEXT_EXTENSIONS:
            return content.decode("utf-8", errors="replace")
        if ext == ".docx":
            return self._read_docx(content)
        if ext == ".pdf":
            reader = self._open_pdf(content)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            # Formulários preenchidos guardam os valores em anotações/campos, fora da camada de texto:
            # só o OCR (que vê a página renderizada) associa cada valor ao seu rótulo.
            if len(text.strip()) >= MIN_PDF_TEXT_CHARS and not self._has_filled_fields(reader):
                return text
            return await self._ocr(content, "application/pdf")
        if ext in IMAGE_MIME:
            return await self._ocr(content, IMAGE_MIME[ext])

        raise ExtractionError(f"Formato não suportado: {ext or 'sem extensão'}")

    @staticmethod
    def _open_pdf(content: bytes) -> PdfReader:
        try:
            return PdfReader(io.BytesIO(content))
        except Exception as exc:
            raise ExtractionError("PDF inválido ou corrompido") from exc

    @staticmethod
    def _has_filled_fields(reader: PdfReader) -> bool:
        if any(field.get("/V") for field in (reader.get_fields() or {}).values()):
            return True
        for page in reader.pages:
            annots = page.get("/Annots")
            for annot in annots.get_object() if annots is not None else []:
                obj = annot.get_object()
                if obj.get("/Subtype") == "/FreeText" and obj.get("/Contents"):
                    return True
        return False

    @staticmethod
    def _read_docx(content: bytes) -> str:
        try:
            doc = DocxDocument(io.BytesIO(content))
        except Exception as exc:
            raise ExtractionError("DOCX inválido ou corrompido") from exc
        lines = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                lines.append(" | ".join(cell.text.strip() for cell in row.cells))
        return "\n".join(lines)

    @staticmethod
    def _render_pdf_pages(content: bytes) -> list[Image.Image]:
        try:
            pdf = pdfium.PdfDocument(content)
        except pdfium.PdfiumError as exc:
            raise ExtractionError("PDF inválido ou corrompido") from exc
        if len(pdf) > MAX_OCR_PAGES:
            raise ExtractionError(f"PDF digitalizado com mais de {MAX_OCR_PAGES} páginas")
        # may_draw_forms inclui na imagem os campos e anotações preenchidos.
        return [page.render(scale=OCR_DPI / 72, may_draw_forms=True).to_pil() for page in pdf]

    @staticmethod
    def _split_into_strips(image: Image.Image) -> list[bytes]:
        """Divide a página em faixas horizontais com sobreposição.

        No modo "high" a OpenAI reduz a imagem até o lado menor ter 768 px; numa página A4 inteira
        a letra manuscrita fica pequena demais. Faixas largas e baixas são enviadas com ~2x a resolução.
        Faixas em branco são descartadas.
        """
        gray = image.convert("L")
        width, height = gray.size
        strip_height = int(width * STRIP_ASPECT)
        step = int(strip_height * (1 - STRIP_OVERLAP))
        strips = []
        for top in range(0, height, step):
            strip = gray.crop((0, top, width, min(top + strip_height, height)))
            if ImageOps.invert(strip).point(lambda p: 255 if p > 80 else 0).getbbox():
                buffer = io.BytesIO()
                strip.save(buffer, format="PNG")
                strips.append(buffer.getvalue())
            if top + strip_height >= height:
                break
        return strips

    @staticmethod
    async def _ocr(content: bytes, mime_type: str) -> str:
        """Transcreve imagens e PDFs digitalizados usando o modelo de visão da OpenAI."""
        from openai import AsyncOpenAI, OpenAIError

        settings = get_settings()
        if not settings.openai_api_key:
            raise ExtractionError("OCR indisponível: defina OPENAI_API_KEY para ler imagens e PDFs digitalizados")

        if mime_type == "application/pdf":
            pages = ExtractionService._render_pdf_pages(content)
        else:
            try:
                pages = [Image.open(io.BytesIO(content))]
            except Exception as exc:
                raise ExtractionError("Imagem inválida ou corrompida") from exc

        message = [{"type": "text", "text": OCR_PROMPT}]
        for number, page in enumerate(pages, start=1):
            message.append({"type": "text", "text": f"Página {number}:"})
            message += [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{base64.b64encode(strip).decode()}", "detail": "high"},
                }
                for strip in ExtractionService._split_into_strips(page)
            ]

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        try:
            response = await client.chat.completions.create(
                model=settings.openai_ocr_model,
                temperature=0,
                messages=[{"role": "user", "content": message}],
            )
        except OpenAIError as exc:
            raise ExtractionError(f"Falha no OCR: {exc}") from exc
        return response.choices[0].message.content or ""
