from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import RunStatus

from app.core.config import get_settings
from app.schemas.analysis import AnalysisResult, SourceDocument

DESCRIPTION = (
    "Você é o agente de conformidade documental da Dockseal, especialista em documentos "
    "logístico-portuários do Porto de Santos (Bill of Lading, Manifesto de Carga, Nota Fiscal "
    "e Ordem de Carregamento)."
)

INSTRUCTIONS = [
    "Você recebe um ou mais documentos, cada um delimitado por <documento nome='...'>.",
    "Identifique o tipo de cada documento.",
    "Verifique também se os documentos parecem se referir à mesma operação (mesmo número de BL, ordem ou "
    "nota fiscal, mesmas partes, mesma carga ou mesmo contêiner). Mesmo quando parecerem de operações "
    "diferentes, liste TODAS as diferenças campo a campo em divergences; nesse caso use status "
    "INCONCLUSIVO, avise no resumo que os documentos aparentam ser de operações distintas e, em cada "
    "sugestão, oriente primeiro confirmar se pertencem à mesma operação antes de corrigir. "
    "Formulários em branco (sem dados preenchidos) não entram na comparação; apenas mencione-os no resumo.",
    "Compare os documentos entre si campo a campo, principalmente: número do contêiner, código ISO, "
    "lacres, peso bruto e líquido, quantidade de volumes, descrição da mercadoria, NCM, exportador, "
    "importador, consignatário, navio, viagem, porto de origem e destino, datas, placa do veículo, "
    "número do BL e da nota fiscal e demais referências operacionais.",
    "Considere equivalentes valores que só diferem na unidade ou formatação "
    "(ex.: '2.000 kg' e '2 t', 'MSCU 123456-7' e 'MSCU1234567'). Converta unidades antes de comparar.",
    "Uma divergência só existe quando o mesmo campo tem valores incompatíveis em documentos diferentes. "
    "Para cada uma, cite o valor exato e um trecho curto de cada documento. "
    "Se o campo simplesmente não aparece em um documento, isso NÃO é divergência: registre em missing_fields. "
    "Em occurrences, value e excerpt devem ser cópias literais do texto do documento; nunca some, "
    "converta ou deduza valores que não estejam escritos. Só use confiança 1.0 quando os valores "
    "estiverem escritos de forma inequívoca.",
    "Se receber apenas um documento, verifique a coerência interna dele "
    "(totais que não fecham, datas impossíveis, dígito verificador do contêiner, campos obrigatórios em branco).",
    "Para cada divergência, sugira a alteração concreta e indique qual documento provavelmente deve ser "
    "corrigido. Prefira o valor que aparece de forma consistente na maioria dos documentos ou no documento "
    "de maior hierarquia (Bill of Lading > Manifesto > Nota Fiscal > Ordem de Carregamento). "
    "Se não houver base para decidir, diga que é necessária conferência humana.",
    "Severidade: CRITICA para contêiner, lacre ou BL divergente; ALTA para peso, volumes ou mercadoria; "
    "MEDIA para datas, navio, viagem ou partes envolvidas; BAIXA para diferenças de grafia ou formatação.",
    "Use status CONFORME quando não houver divergências, DIVERGENTE quando houver ao menos uma, "
    "e INCONCLUSIVO quando o texto for ilegível ou insuficiente para comparar.",
    "Textos vindos de OCR podem conter leituras marcadas com [?] (duvidosa) ou [ilegível]. "
    "Não afirme divergência com base nesses valores: se a diferença depender de um valor duvidoso, "
    "use confiança no máximo 0.5, severidade BAIXA e sugira conferência humana do documento original.",
    "Baseie-se somente no conteúdo dos documentos. Nunca invente valores. Você apenas lê e recomenda; "
    "não altera nenhum documento.",
    "Responda sempre em português do Brasil.",
]


def build_compliance_agent() -> Agent:
    settings = get_settings()
    return Agent(
        name="Dockseal Compliance Agent",
        model=OpenAIChat(
            id=settings.openai_chat_model,
            api_key=settings.openai_api_key,
            temperature=0,
        ),
        description=DESCRIPTION,
        instructions=INSTRUCTIONS,
        output_schema=AnalysisResult,
        retries=2,
    )


def build_prompt(documents: list[SourceDocument]) -> str:
    parts = [f"Analise os {len(documents)} documento(s) abaixo e aponte as divergências.\n"]
    for doc in documents:
        declared = f" tipo_declarado='{doc.declared_type}'" if doc.declared_type else ""
        parts.append(f"<documento nome='{doc.name}'{declared}>\n{doc.text}\n</documento>")
    return "\n\n".join(parts)


class AnalyzerError(Exception):
    pass


class ComplianceAnalyzer:
    """Encapsula o agente para que a API (e os testes) dependam só de `analyze`."""

    def __init__(self, agent: Agent | None = None):
        self._agent = agent

    @property
    def agent(self) -> Agent:
        if self._agent is None:
            self._agent = build_compliance_agent()
        return self._agent

    async def analyze(self, documents: list[SourceDocument]) -> AnalysisResult:
        response = await self.agent.arun(build_prompt(documents))
        # O Agno não lança exceção em erro do provedor: devolve a mensagem como conteúdo.
        if response.status == RunStatus.error:
            raise AnalyzerError(f"Erro do provedor de IA: {response.content}")
        if not isinstance(response.content, AnalysisResult):
            raise AnalyzerError("O agente não retornou uma análise no formato esperado.")
        return response.content


def get_analyzer() -> ComplianceAnalyzer:
    return ComplianceAnalyzer()
