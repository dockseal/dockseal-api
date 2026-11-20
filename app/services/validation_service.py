import re
import unicodedata
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.compliance_agent import ComplianceAnalyzer
from app.models import Alert, Shipment, Validation
from app.schemas.analysis import AnalysisResult, AnalysisStatus, Divergence, Severity, SourceDocument
from app.services.audit_service import register_event

# Divergências a partir desta severidade viram alerta.
ALERT_SEVERITIES = {Severity.MEDIA, Severity.ALTA, Severity.CRITICA}
SEVERITY_RANK = {Severity.BAIXA: 0, Severity.MEDIA: 1, Severity.ALTA: 2, Severity.CRITICA: 3}
SUGGESTION_MARKER = "Sugestão:"
MISSING_DIVERGENCE_NOTE = "Divergência não encontrada na nova análise."
_PARENTHETICAL = re.compile(r"\([^)]*\)")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_field(value: str) -> str:
    without_notes = _PARENTHETICAL.sub(" ", value)
    decomposed = unicodedata.normalize("NFKD", without_notes)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    cleaned = _NON_WORD.sub(" ", without_accents.casefold())
    return " ".join(cleaned.split())


def recorded_field_name(alert: Alert) -> str:
    if alert.field and alert.field.strip():
        return alert.field.strip()
    description = alert.description or ""
    separator = description.find(":")
    suggestion_index = description.find(SUGGESTION_MARKER)
    has_field = separator > 0 and (suggestion_index < 0 or separator < suggestion_index)
    if not has_field:
        return ""
    return description[:separator].strip()


def alert_field_key(alert: Alert) -> str:
    return normalize_field(recorded_field_name(alert))


def known_field_names(alerts: list[Alert]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for alert in alerts:
        label = recorded_field_name(alert)
        key = normalize_field(label)
        if not key or key in seen:
            continue
        seen.add(key)
        names.append(label)
    return names


def divergence_description(divergence: Divergence) -> str:
    return f"{divergence.field}: {divergence.description} {SUGGESTION_MARKER} {divergence.suggestion}"


def sync_shipment_review_status(
    db: Session,
    shipment: Shipment | None,
    analysis_status: str | None = None,
) -> None:
    """Pendência fica só com alerta aberto ou com análise sem alerta acionável."""
    if shipment is None or (shipment.status == "REGISTERED" and analysis_status is None):
        return

    db.flush()
    open_alert = db.scalar(
        select(Alert.id).where(Alert.shipment_id == shipment.id, Alert.status == "OPEN").limit(1)
    )
    if open_alert is not None:
        shipment.status = "PENDING_REVIEW"
        return

    has_alert = db.scalar(select(Alert.id).where(Alert.shipment_id == shipment.id).limit(1))
    if has_alert is not None:
        shipment.status = "VALIDATED"
        return

    if analysis_status is None:
        analysis_status = db.scalar(
            select(Validation.status)
            .where(Validation.shipment_id == shipment.id)
            .order_by(Validation.created_at.desc())
            .limit(1)
        )

    if analysis_status in {AnalysisStatus.INCONCLUSIVO.value, AnalysisStatus.DIVERGENTE.value}:
        shipment.status = "PENDING_REVIEW"
        return

    shipment.status = "VALIDATED"


class ValidationService:
    def __init__(self, db: Session, analyzer: ComplianceAnalyzer):
        self.db = db
        self.analyzer = analyzer

    async def compare_documents(
        self, documents: list[SourceDocument], known_fields: list[str] | None = None
    ) -> AnalysisResult:
        return await self.analyzer.analyze(documents, known_fields=known_fields)

    async def validate_shipment(self, shipment: Shipment, user_id: uuid.UUID) -> Validation:
        documents = [
            SourceDocument(name=doc.filename, text=doc.extraction.text, declared_type=doc.type.value)
            for doc in shipment.documents
            if doc.extraction is not None
        ]
        if not documents:
            raise ValueError("O embarque não possui documentos com texto extraído para analisar.")

        existing = list(self.db.scalars(select(Alert).where(Alert.shipment_id == shipment.id)).all())
        result = await self.compare_documents(documents, known_field_names(existing))
        validation = self.save_validation(result, shipment_id=shipment.id)
        self.generate_alerts(validation, result, shipment_id=shipment.id)
        sync_shipment_review_status(self.db, shipment, result.status.value)
        register_event(
            self.db,
            "VALIDATION",
            status=result.status.value,
            user_id=user_id,
            shipment_id=shipment.id,
            observation=f"{len(result.divergences)} divergência(s) encontrada(s)",
        )
        self.db.commit()
        return validation

    def save_validation(self, result: AnalysisResult, shipment_id: uuid.UUID | None = None) -> Validation:
        validation = Validation(
            status=result.status.value,
            details=result.summary,
            result=result.model_dump(mode="json"),
            confidence_score=result.confidence,
            shipment_id=shipment_id,
        )
        self.db.add(validation)
        return validation

    def generate_alerts(
        self, validation: Validation, result: AnalysisResult, shipment_id: uuid.UUID | None
    ) -> list[Alert]:
        divergences = _strongest_by_field(
            [divergence for divergence in result.divergences if divergence.severity in ALERT_SEVERITIES]
        )
        if shipment_id is None:
            alerts = [_new_alert(divergence, shipment_id, validation) for divergence in divergences.values()]
            self.db.add_all(alerts)
            return alerts

        existing = list(self.db.scalars(select(Alert).where(Alert.shipment_id == shipment_id)).all())
        grouped: dict[str, list[Alert]] = {}
        for alert in existing:
            grouped.setdefault(alert_field_key(alert), []).append(alert)

        seen: set[str] = set()
        kept: list[Alert] = []
        for key, divergence in divergences.items():
            seen.add(key)
            matches = grouped.get(key, [])
            if not matches:
                alert = _new_alert(divergence, shipment_id, validation)
                self.db.add(alert)
                kept.append(alert)
                continue
            keeper = _preferred_alert(matches)
            keeper.field = divergence.field
            keeper.severity = divergence.severity.value
            keeper.description = divergence_description(divergence)
            keeper.validation = validation
            kept.append(keeper)
            for extra in matches:
                if extra is not keeper and extra.status == "OPEN":
                    extra.resolve()

        for alert in existing:
            if alert_field_key(alert) in seen or alert.status != "OPEN":
                continue
            alert.resolve()
            if not alert.resolution_note:
                alert.resolution_note = MISSING_DIVERGENCE_NOTE
        return kept


def _strongest_by_field(divergences: list[Divergence]) -> dict[str, Divergence]:
    chosen: dict[str, Divergence] = {}
    for divergence in divergences:
        key = normalize_field(divergence.field)
        if not key:
            continue
        current = chosen.get(key)
        if current is None or SEVERITY_RANK[divergence.severity] > SEVERITY_RANK[current.severity]:
            chosen[key] = divergence
    return chosen


def _new_alert(divergence: Divergence, shipment_id: uuid.UUID | None, validation: Validation) -> Alert:
    return Alert(
        field=divergence.field,
        severity=divergence.severity.value,
        description=divergence_description(divergence),
        shipment_id=shipment_id,
        validation=validation,
    )


def _preferred_alert(matches: list[Alert]) -> Alert:
    treated = [alert for alert in matches if alert.status != "OPEN"]
    pool = treated or matches
    return min(pool, key=lambda alert: (alert.created_at, str(alert.id)))
