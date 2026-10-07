import uuid

from sqlalchemy.orm import Session

from app.agents.compliance_agent import ComplianceAnalyzer
from app.models import Alert, Shipment, Validation
from app.schemas.analysis import AnalysisResult, AnalysisStatus, Severity, SourceDocument
from app.services.audit_service import register_event

# Divergências a partir desta severidade viram alerta.
ALERT_SEVERITIES = {Severity.MEDIA, Severity.ALTA, Severity.CRITICA}


class ValidationService:
    def __init__(self, db: Session, analyzer: ComplianceAnalyzer):
        self.db = db
        self.analyzer = analyzer

    async def compare_documents(self, documents: list[SourceDocument]) -> AnalysisResult:
        return await self.analyzer.analyze(documents)

    async def validate_shipment(self, shipment: Shipment, user_id: uuid.UUID) -> Validation:
        documents = [
            SourceDocument(name=doc.filename, text=doc.extraction.text, declared_type=doc.type.value)
            for doc in shipment.documents
            if doc.extraction is not None
        ]
        if not documents:
            raise ValueError("O embarque não possui documentos com texto extraído para analisar.")

        result = await self.compare_documents(documents)
        validation = self.save_validation(result, shipment_id=shipment.id)
        self.generate_alerts(validation, result, shipment_id=shipment.id)

        shipment.status = "VALIDATED" if result.status == AnalysisStatus.CONFORME else "PENDING_REVIEW"
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

    def generate_alerts(self, validation: Validation, result: AnalysisResult, shipment_id: uuid.UUID | None) -> list[Alert]:
        alerts = [
            Alert(
                severity=div.severity.value,
                description=f"{div.field}: {div.description} Sugestão: {div.suggestion}",
                shipment_id=shipment_id,
                validation=validation,
            )
            for div in result.divergences
            if div.severity in ALERT_SEVERITIES
        ]
        self.db.add_all(alerts)
        return alerts
