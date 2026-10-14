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
    shipments_in_yard = sum(1 for shipment in shipments if shipment.returned_at is None)

    samples: list[float] = []
    for shipment in shipments:
        if shipment.dispatched_at is None or shipment.returned_at is None:
            continue
        elapsed = _as_utc(shipment.returned_at) - _as_utc(shipment.dispatched_at)
        samples.append(elapsed.total_seconds() / 3600)
    average_transit_hours = round(sum(samples) / len(samples), 2) if samples else None

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
        shipments_in_yard=shipments_in_yard,
        average_transit_hours=average_transit_hours,
        efficiency_percent=efficiency_percent,
        volume_trend=volume_trend,
    )
