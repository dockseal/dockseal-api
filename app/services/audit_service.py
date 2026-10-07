import uuid

from sqlalchemy.orm import Session

from app.models import ProcessEvent


def register_event(
    db: Session,
    step: str,
    status: str = "SUCCESS",
    *,
    user_id: uuid.UUID | None = None,
    shipment_id: uuid.UUID | None = None,
    observation: str | None = None,
) -> ProcessEvent:
    """Registra um evento na trilha de auditoria. Não faz commit: entra na transação de quem chamou."""
    event = ProcessEvent(
        step=step, status=status, user_id=user_id, shipment_id=shipment_id, observation=observation
    )
    db.add(event)
    return event
