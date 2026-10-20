from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_permission
from app.models import User
from app.schemas.api import DashboardMetrics
from app.services.auth_service import Permissions
from app.services.metrics_service import compute_metrics

router = APIRouter(tags=["Dashboard"])

_CACHE_TTL = timedelta(minutes=5)
_cache: tuple[datetime, DashboardMetrics] | None = None


def clear_dashboard_cache() -> None:
    global _cache
    _cache = None


@router.get("/dashboard/metrics", response_model=DashboardMetrics, summary="Indicadores do dashboard")
def dashboard_metrics(
    db: DbSession,
    _: Annotated[User, Depends(require_permission(Permissions.SHIPMENT_READ))],
):
    """Agregações calculadas na API. A resposta fica em cache por 5 minutos neste processo."""
    global _cache
    now = datetime.now(UTC)
    if _cache is not None and now - _cache[0] < _CACHE_TTL:
        return _cache[1]
    metrics = compute_metrics(db)
    _cache = (now, metrics)
    return metrics
