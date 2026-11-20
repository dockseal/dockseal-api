from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Shipment
from app.schemas.api import DashboardMetrics, VolumeTrendPoint


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def compute_metrics(db: Session) -> DashboardMetrics:
    shipments = list(db.scalars(select(Shipment)).all())

    validated = sum(1 for shipment in shipments if shipment.status == "VALIDATED")
    pending = sum(1 for shipment in shipments if shipment.status == "PENDING_REVIEW")
    denominator = validated + pending
    efficiency_percent = round(validated / denominator * 100, 2) if denominator else None

    today = datetime.now(UTC).date()
    start = today - timedelta(days=29)
    counts = {start + timedelta(days=offset): 0 for offset in range(30)}
    for shipment in shipments:
        day = _as_utc(shipment.created_at).date()
        if day in counts:
            counts[day] += 1
    volume_trend = [VolumeTrendPoint(date=day.isoformat(), count=counts[day]) for day in sorted(counts)]

    return DashboardMetrics(
        efficiency_percent=efficiency_percent,
        volume_trend=volume_trend,
    )
