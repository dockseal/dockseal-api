import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.schema_migration import ensure_schema
from app.models import Container


def test_ensure_schema_adds_columns_and_backfills_once():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    container_id = uuid.uuid4()
    shipment_id = uuid.uuid4()
    now = datetime.now(UTC)

    with Session(engine) as db:
        db.add(Container(id=container_id, container_number="MSCU7742123", status="AVAILABLE"))
        db.commit()

    with engine.begin() as connection:
        connection.execute(text("DROP TABLE shipment_container"))
        connection.execute(text("DROP INDEX IF EXISTS ix_shipment_shipment_id_custom"))
        connection.execute(text("DROP INDEX IF EXISTS uq_shipment_custom_id"))
        connection.execute(text("ALTER TABLE shipment DROP COLUMN shipment_id_custom"))
        connection.execute(text("ALTER TABLE shipment DROP COLUMN transport_company"))
        connection.execute(text("ALTER TABLE shipment DROP COLUMN expected_arrival"))
        connection.execute(text("ALTER TABLE alert DROP COLUMN resolution_note"))
        connection.execute(
            text(
                """
                INSERT INTO shipment (
                    id, origin, destination, dispatched_at, expected_return, returned_at,
                    status, container_id, created_at, updated_at
                ) VALUES (
                    :id, 'Santos', 'Roterdã', NULL, NULL, NULL,
                    'REGISTERED', :container_id, :now, :now
                )
                """
            ),
            {"id": str(shipment_id), "container_id": str(container_id), "now": now},
        )

    Base.metadata.create_all(engine)
    ensure_schema(engine)

    from sqlalchemy import inspect

    shipment_columns = {column["name"] for column in inspect(engine).get_columns("shipment")}
    alert_columns = {column["name"] for column in inspect(engine).get_columns("alert")}
    assert {"shipment_id_custom", "transport_company", "expected_arrival"} <= shipment_columns
    assert "resolution_note" in alert_columns

    with engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM shipment_container")).scalar()
    assert count == 1

    ensure_schema(engine)
    with engine.connect() as connection:
        count_again = connection.execute(text("SELECT COUNT(*) FROM shipment_container")).scalar()
    assert count_again == 1
