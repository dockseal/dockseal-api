from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.models import Shipment, ShipmentContainer


def ensure_schema(engine) -> None:
    """Acrescenta colunas e o índice único em bancos já criados e preenche a associação de contêineres."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    date_type = "TIMESTAMP" if engine.dialect.name == "postgresql" else "DATETIME"
    statements: list[str] = []

    if "shipment" in tables:
        columns = {column["name"] for column in inspector.get_columns("shipment")}
        if "shipment_id_custom" not in columns:
            statements.append("ALTER TABLE shipment ADD COLUMN shipment_id_custom VARCHAR(50)")
        if "transport_company" not in columns:
            statements.append("ALTER TABLE shipment ADD COLUMN transport_company VARCHAR(150)")
        if "expected_arrival" not in columns:
            statements.append(f"ALTER TABLE shipment ADD COLUMN expected_arrival {date_type}")
        index_names = {index["name"] for index in inspector.get_indexes("shipment")}
        if "uq_shipment_custom_id" not in index_names:
            statements.append(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_shipment_custom_id ON shipment (shipment_id_custom)"
            )

    if "alert" in tables:
        columns = {column["name"] for column in inspector.get_columns("alert")}
        if "resolution_note" not in columns:
            statements.append("ALTER TABLE alert ADD COLUMN resolution_note TEXT")

    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))

    refreshed = set(inspect(engine).get_table_names())
    if "shipment" not in refreshed or "shipment_container" not in refreshed:
        return

    with Session(engine) as db:
        shipments = db.scalars(select(Shipment).where(Shipment.container_id.is_not(None))).all()
        for shipment in shipments:
            exists = db.scalar(
                select(ShipmentContainer.id).where(
                    ShipmentContainer.shipment_id == shipment.id,
                    ShipmentContainer.container_id == shipment.container_id,
                )
            )
            if exists is None and shipment.container_id is not None:
                db.add(ShipmentContainer(shipment_id=shipment.id, container_id=shipment.container_id))
        db.commit()
