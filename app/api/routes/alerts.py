import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, select

from app.api.deps import DbSession, require_permission
from app.models import Alert, ProcessEvent, User
from app.schemas.api import AlertOut, AlertSeverity, AlertStatus, AlertStatusIn, ProcessEventOut
from app.services.audit_service import register_event
from app.services.auth_service import Permissions

router = APIRouter(tags=["Alertas e histórico"])

SEVERITY_ORDER = case(
    {"CRITICA": 0, "ALTA": 1, "MEDIA": 2, "BAIXA": 3},
    value=Alert.severity,
    else_=4,
)


@router.get("/alerts", response_model=list[AlertOut], summary="Listar alertas")
def list_alerts(
    db: DbSession,
    _: Annotated[User, Depends(require_permission(Permissions.ALERT_READ))],
    status_filter: Annotated[AlertStatus | None, Query(alias="status")] = None,
    severity: AlertSeverity | None = None,
    shipment_id: uuid.UUID | None = None,
):
    """Ordenados por criticidade (CRITICA primeiro) e depois pelos mais recentes. Todos os filtros são opcionais."""
    query = select(Alert).order_by(SEVERITY_ORDER, Alert.created_at.desc())
    if status_filter:
        query = query.where(Alert.status == status_filter)
    if severity:
        query = query.where(Alert.severity == severity)
    if shipment_id:
        query = query.where(Alert.shipment_id == shipment_id)
    return db.scalars(query).all()


@router.patch(
    "/alerts/{alert_id}",
    response_model=AlertOut,
    summary="Mudar status do alerta",
    responses={404: {"description": "Alerta não encontrado"}},
)
def update_alert(
    db: DbSession,
    user: Annotated[User, Depends(require_permission(Permissions.ALERT_MANAGE))],
    alert_id: uuid.UUID,
    data: AlertStatusIn,
):
    """Corpo JSON: `{"status": "OPEN" | "RESOLVED" | "CLOSED"}`."""
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Alerta não encontrado")
    {"OPEN": alert.open, "RESOLVED": alert.resolve, "CLOSED": alert.close}[data.status]()
    register_event(db, f"ALERT_{data.status}", user_id=user.id, shipment_id=alert.shipment_id, observation=str(alert.id))
    db.commit()
    return alert


@router.get("/events", response_model=list[ProcessEventOut], summary="Histórico operacional (auditoria)")
def list_events(
    db: DbSession,
    _: Annotated[User, Depends(require_permission(Permissions.HISTORY_READ))],
    shipment_id: uuid.UUID | None = None,
    limit: int = 100,
):
    """Mais recentes primeiro. Registra logins, cadastros, uploads, análises e mudanças de alertas."""
    query = select(ProcessEvent).order_by(ProcessEvent.created_at.desc()).limit(limit)
    if shipment_id:
        query = query.where(ProcessEvent.shipment_id == shipment_id)
    return db.scalars(query).all()
