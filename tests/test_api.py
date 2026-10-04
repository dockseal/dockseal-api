import io

from docx import Document as DocxDocument


def docx_bytes(text: str) -> bytes:
    doc = DocxDocument()
    doc.add_paragraph(text)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


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
