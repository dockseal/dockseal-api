import io
import uuid

from docx import Document as DocxDocument


def docx_bytes(text: str) -> bytes:
    doc = DocxDocument()
    doc.add_paragraph(text)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def test_password_is_stored_as_argon2_hash(session_factory):
    from sqlalchemy import select

    from app.models import User

    with session_factory() as db:
        user = db.scalar(select(User).where(User.email == "operador@dockseal.com"))
    assert user.password_hash.startswith("$argon2id$")
    assert "senha123" not in user.password_hash


def test_ids_are_uuids(client, operator_headers):
    response = client.get("/auth/me", headers=operator_headers)
    assert uuid.UUID(response.json()["id"]).version == 4


def test_invalid_uuid_is_rejected(client, operator_headers):
    assert client.get("/shipments/123", headers=operator_headers).status_code == 422
    assert client.get(f"/shipments/{uuid.uuid4()}", headers=operator_headers).status_code == 404


def test_login_with_invalid_password(client):
    response = client.post("/auth/login", data={"username": "operador@dockseal.com", "password": "errada"})
    assert response.status_code == 401


def test_me_requires_token(client):
    assert client.get("/auth/me").status_code == 401


def test_me_returns_user(client, operator_headers):
    response = client.get("/auth/me", headers=operator_headers)
    assert response.status_code == 200
    assert response.json()["role"]["name"] == "OPERADOR"


def test_analysis_finds_divergence_between_documents(client, operator_headers, analyzer):
    files = [
        ("files", ("bl.txt", b"Bill of Lading\nPeso: 2000 kg", "text/plain")),
        (
            "files",
            (
                "nota.docx",
                docx_bytes("Nota Fiscal\nPeso: 10000 kg"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        ),
    ]
    response = client.post("/analysis", headers=operator_headers, files=files)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "DIVERGENTE"
    assert body["divergences"][0]["field"] == "peso bruto"
    assert [d.name for d in analyzer.received] == ["bl.txt", "nota.docx"]
    assert "10000 kg" in analyzer.received[1].text


def test_analysis_rejects_unsupported_file(client, operator_headers):
    files = [("files", ("planilha.exe", b"xx", "application/octet-stream"))]
    response = client.post("/analysis", headers=operator_headers, files=files)
    assert response.status_code == 415


def test_shipment_flow_generates_alert(client, operator_headers, manager_headers):
    shipment = client.post(
        "/shipments",
        headers=operator_headers,
        json={"origin": "Santos", "destination": "Roterdã", "container": {"container_number": "MSCU 123456-7"}},
    )
    assert shipment.status_code == 201, shipment.text
    shipment_id = shipment.json()["id"]
    assert shipment.json()["container"]["container_number"] == "MSCU1234567"

    upload = client.post(
        f"/shipments/{shipment_id}/documents",
        headers=operator_headers,
        files=[
            ("files", ("bl.txt", b"Peso: 2000 kg", "text/plain")),
            ("files", ("manifesto.txt", b"Peso: 10000 kg", "text/plain")),
        ],
        data={"types": ["BILL_OF_LADING", "MANIFESTO_CARGA"]},
    )
    assert upload.status_code == 201, upload.text

    validation = client.post(f"/shipments/{shipment_id}/validate", headers=operator_headers)
    assert validation.status_code == 200, validation.text
    assert validation.json()["status"] == "DIVERGENTE"

    detail = client.get(f"/shipments/{shipment_id}", headers=operator_headers).json()
    assert detail["status"] == "PENDING_REVIEW"
    assert len(detail["documents"]) == 2

    alerts = client.get("/alerts", headers=manager_headers, params={"shipment_id": shipment_id}).json()
    assert len(alerts) == 1 and alerts[0]["severity"] == "ALTA"

    resolved = client.patch(f"/alerts/{alerts[0]['id']}", headers=manager_headers, json={"status": "RESOLVED"})
    assert resolved.json()["status"] == "RESOLVED"

    events = client.get("/events", headers=manager_headers, params={"shipment_id": shipment_id}).json()
    assert {e["step"] for e in events} >= {"SHIPMENT_CREATED", "DOCUMENTS_UPLOADED", "VALIDATION"}


def test_operator_cannot_read_history(client, operator_headers):
    assert client.get("/events", headers=operator_headers).status_code == 403


def test_me_lists_permissions(client, manager_headers):
    body = client.get("/auth/me", headers=manager_headers).json()
    assert "history:read" in body["permissions"]
    assert "shipment:write" not in body["permissions"]


def test_cors_allows_frontend_origin(client):
    response = client.options(
        "/auth/login",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_dates_are_returned_in_utc(client, operator_headers):
    created = client.post(
        "/shipments",
        headers=operator_headers,
        json={"origin": "Santos", "destination": "Roterdã", "dispatched_at": "2026-10-03T10:00:00Z"},
    ).json()
    listed = client.get("/shipments", headers=operator_headers).json()[0]
    assert created["dispatched_at"] == listed["dispatched_at"] == "2026-10-03T10:00:00Z"
    assert listed["created_at"].endswith("Z")


def test_alerts_filter_by_status(client, manager_headers):
    assert client.get("/alerts", headers=manager_headers, params={"status": "OPEN"}).status_code == 200
    assert client.get("/alerts", headers=manager_headers, params={"status": "XYZ"}).status_code == 422


def test_expected_arrival_in_the_past_is_rejected(client, operator_headers):
    response = client.post(
        "/shipments",
        headers=operator_headers,
        json={"origin": "Santos", "destination": "Roterdã", "expected_arrival": "2020-01-01T00:00:00Z"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Data de chegada prevista não pode ser anterior a hoje"


def test_shipment_accepts_custom_id_company_and_future_arrival(client, operator_headers):
    response = client.post(
        "/shipments",
        headers=operator_headers,
        json={
            "origin": "Santos",
            "destination": "Roterdã",
            "shipment_id_custom": "SHP-2026-1",
            "transport_company": "MSC",
            "expected_arrival": "2099-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["shipment_id_custom"] == "SHP-2026-1"
    assert body["transport_company"] == "MSC"
    assert body["expected_arrival"] == "2099-01-01T00:00:00Z"

    duplicate = client.post(
        "/shipments",
        headers=operator_headers,
        json={"origin": "Santos", "destination": "Roterdã", "shipment_id_custom": "SHP-2026-1"},
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["detail"] == "Identificador de embarque já cadastrado"


def test_container_must_match_iso_6346(client, operator_headers):
    response = client.post(
        "/shipments",
        headers=operator_headers,
        json={"origin": "Santos", "destination": "Roterdã", "container": {"container_number": "ABC123"}},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Número de contêiner inválido. Use o padrão ISO 6346: 4 letras e 7 números."


def test_container_in_transit_on_another_open_shipment_is_rejected(client, operator_headers, session_factory):
    from datetime import UTC, datetime

    from app.models import Shipment

    first = client.post(
        "/shipments",
        headers=operator_headers,
        json={"origin": "Santos", "destination": "Roterdã"},
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]
    attached = client.post(
        f"/shipments/{first_id}/containers",
        headers=operator_headers,
        json={"container_number": "MSCU7742123"},
    )
    assert attached.status_code == 200, attached.text

    second = client.post(
        "/shipments",
        headers=operator_headers,
        json={"origin": "Santos", "destination": "Roterdã"},
    )
    second_id = second.json()["id"]
    blocked = client.post(
        f"/shipments/{second_id}/containers",
        headers=operator_headers,
        json={"container_number": "MSCU7742123"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["detail"] == "Contêiner já está em trânsito em outro embarque"

    added = client.post(
        f"/shipments/{first_id}/containers",
        headers=operator_headers,
        json={"container_number": "MSCU7742124"},
    )
    assert added.status_code == 200, added.text
    body = added.json()
    assert body["container"]["container_number"] == "MSCU7742123"
    assert [item["container_number"] for item in body["containers"]] == ["MSCU7742123", "MSCU7742124"]

    repeated = client.post(
        f"/shipments/{first_id}/containers",
        headers=operator_headers,
        json={"container_number": "MSCU7742124"},
    )
    assert repeated.status_code == 200, repeated.text
    assert len(repeated.json()["containers"]) == 2

    with session_factory() as db:
        shipment = db.get(Shipment, uuid.UUID(first_id))
        shipment.returned_at = datetime.now(UTC)
        db.commit()

    third = client.post(
        "/shipments",
        headers=operator_headers,
        json={"origin": "Santos", "destination": "Roterdã"},
    )
    reused = client.post(
        f"/shipments/{third.json()['id']}/containers",
        headers=operator_headers,
        json={"container_number": "MSCU7742123"},
    )
    assert reused.status_code == 200, reused.text

    replaced = client.put(
        f"/shipments/{first_id}/container",
        headers=operator_headers,
        json={"container_number": "MSCU7742125"},
    )
    assert replaced.status_code == 200, replaced.text
    replaced_body = replaced.json()
    assert replaced_body["container"]["container_number"] == "MSCU7742125"
    assert [item["container_number"] for item in replaced_body["containers"]] == [
        "MSCU7742123",
        "MSCU7742124",
        "MSCU7742125",
    ]


def test_dismiss_alert_stores_resolution_note(client, manager_headers, session_factory):
    from app.models import Alert

    with session_factory() as db:
        alert = Alert(severity="ALTA", description="Lacre divergente", status="OPEN")
        db.add(alert)
        db.commit()
        alert_id = str(alert.id)

    response = client.patch(
        f"/alerts/{alert_id}",
        headers=manager_headers,
        json={"status": "DISMISSED", "resolution_note": "Falso positivo"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "DISMISSED"
    assert body["resolution_note"] == "Falso positivo"
    assert body["updated_at"]

    listed = client.get("/alerts", headers=manager_headers, params={"status": "DISMISSED"}).json()
    assert any(item["id"] == alert_id for item in listed)


def test_shipment_events_are_newest_first_and_restricted(client, operator_headers, manager_headers):
    shipment = client.post(
        "/shipments",
        headers=operator_headers,
        json={"origin": "Santos", "destination": "Roterdã"},
    )
    shipment_id = shipment.json()["id"]
    upload = client.post(
        f"/shipments/{shipment_id}/documents",
        headers=operator_headers,
        files=[("files", ("bl.txt", b"Peso: 1 kg", "text/plain"))],
    )
    assert upload.status_code == 201, upload.text

    events = client.get(f"/shipments/{shipment_id}/events", headers=manager_headers)
    assert events.status_code == 200, events.text
    assert [item["step"] for item in events.json()][:2] == ["DOCUMENTS_UPLOADED", "SHIPMENT_CREATED"]
    assert client.get(f"/shipments/{uuid.uuid4()}/events", headers=manager_headers).status_code == 404
    assert client.get(f"/shipments/{shipment_id}/events", headers=operator_headers).status_code == 403


def test_login_returns_refresh_token_and_user(client):
    response = client.post("/auth/login", data={"username": "operador@dockseal.com", "password": "senha123"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["refresh_token"]
    assert body["user"]["role"] == "OPERADOR"
    assert uuid.UUID(body["user"]["id"]).version == 4

    refreshed = client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert refreshed.status_code == 200, refreshed.text
    access_token = refreshed.json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me.status_code == 200

    rejected = client.post("/auth/refresh", json={"refresh_token": body["access_token"]})
    assert rejected.status_code == 401
    assert rejected.json()["detail"] == "Refresh token inválido"
    assert client.post("/auth/refresh", json={}).status_code == 422


def test_invoice_alias_and_container_photo_evidence(client, operator_headers):
    shipment = client.post(
        "/shipments",
        headers=operator_headers,
        json={"origin": "Santos", "destination": "Roterdã"},
    )
    shipment_id = shipment.json()["id"]

    invoice = client.post(
        f"/shipments/{shipment_id}/documents",
        headers=operator_headers,
        files=[("files", ("nota.txt", b"Nota Fiscal", "text/plain"))],
        data={"types": "INVOICE"},
    )
    assert invoice.status_code == 201, invoice.text
    assert invoice.json()[0]["type"] == "NOTA_FISCAL"

    photo = client.post(
        f"/shipments/{shipment_id}/documents",
        headers=operator_headers,
        files=[("files", ("lacre.txt", b"Lacre: SL-1", "text/plain"))],
        data={"types": "CONTAINER_PHOTO"},
    )
    assert photo.status_code == 201, photo.text
    assert photo.json() == []

    detail = client.get(f"/shipments/{shipment_id}", headers=operator_headers).json()
    assert len(detail["documents"]) == 1
    assert detail["evidences"][0]["type"] == "FOTO_CONTAINER"

    invalid = client.post(
        f"/shipments/{shipment_id}/documents",
        headers=operator_headers,
        files=[("files", ("x.txt", b"texto", "text/plain"))],
        data={"types": "FOO"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "Tipo de documento inválido"


def test_dashboard_metrics(client, operator_headers, session_factory):
    from datetime import UTC, datetime, timedelta

    from app.api.routes.dashboard import clear_dashboard_cache
    from app.models import Shipment

    now = datetime.now(UTC)
    with session_factory() as db:
        db.add(Shipment(origin="Santos", destination="Roterdã", status="REGISTERED"))
        db.add(
            Shipment(
                origin="Santos",
                destination="Roterdã",
                status="REGISTERED",
                dispatched_at=now - timedelta(hours=3),
                returned_at=now,
            )
        )
        db.add(Shipment(origin="Santos", destination="Roterdã", status="VALIDATED"))
        db.add(Shipment(origin="Santos", destination="Roterdã", status="PENDING_REVIEW"))
        db.commit()

    clear_dashboard_cache()
    body = client.get("/dashboard/metrics", headers=operator_headers).json()
    assert body["average_transit_hours"] == 3.0
    assert body["efficiency_percent"] == 50.0
    assert len(body["volume_trend"]) == 30


def test_validate_new_password_rules():
    import pytest

    from app.core.security import validate_new_password

    with pytest.raises(ValueError):
        validate_new_password("senha123")
    validate_new_password("Password@123")
