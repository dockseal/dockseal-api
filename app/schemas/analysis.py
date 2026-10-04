from enum import StrEnum

from pydantic import BaseModel, Field


class Severity(StrEnum):
    BAIXA = "BAIXA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    CRITICA = "CRITICA"


class AnalysisStatus(StrEnum):
    CONFORME = "CONFORME"
    DIVERGENTE = "DIVERGENTE"
    INCONCLUSIVO = "INCONCLUSIVO"


class FieldOccurrence(BaseModel):
    document: str = Field(description="Nome do arquivo em que o valor aparece")
    value: str = Field(description="Valor exatamente como aparece no documento")
    excerpt: str | None = Field(default=None, description="Trecho curto do documento que comprova o valor")


class Divergence(BaseModel):
    field: str = Field(description="Campo divergente, ex.: 'peso bruto', 'número do contêiner', 'lacre'")
    description: str = Field(description="Explicação objetiva da divergência")
    occurrences: list[FieldOccurrence] = Field(description="Valor encontrado em cada documento envolvido")
    severity: Severity
    suggestion: str = Field(description="Sugestão de alteração para sanar a divergência")
    document_to_fix: str | None = Field(
        default=None, description="Documento que provavelmente precisa ser corrigido, se for possível inferir"
    )
    confidence: float = Field(ge=0, le=1, description="Confiança de 0 a 1 de que a divergência é real")


class MissingField(BaseModel):
    field: str
    present_in: list[str] = Field(description="Documentos em que o campo aparece")
    missing_in: list[str] = Field(description="Documentos em que o campo deveria aparecer mas está ausente")
    suggestion: str


class AnalyzedDocument(BaseModel):
    document: str = Field(description="Nome do arquivo")
    identified_type: str = Field(
        description="Tipo identificado: BILL_OF_LADING, MANIFESTO_CARGA, NOTA_FISCAL, ORDEM_CARREGAMENTO ou OUTRO"
    )


class AnalysisResult(BaseModel):
    """Saída estruturada do agente de conformidade documental."""

    status: AnalysisStatus
    summary: str = Field(description="Resumo em português da análise e da resolução sugerida")
    documents: list[AnalyzedDocument]
    divergences: list[Divergence] = Field(default_factory=list)
    missing_fields: list[MissingField] = Field(default_factory=list)
    consistent_fields: list[str] = Field(
        default_factory=list, description="Campos conferidos que estão coerentes entre os documentos"
    )
    confidence: float = Field(ge=0, le=1, description="Confiança geral da análise")


class SourceDocument(BaseModel):
    """Documento já convertido em texto, pronto para ser enviado ao agente."""

    name: str
    text: str
    declared_type: str | None = None
