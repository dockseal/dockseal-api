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
        json={"origin": "Santos", "destination": "Roterdã", "container": {"container_number": "MSCU 123456-6"}},
    )
    assert shipment.status_code == 201, shipment.text
    shipment_id = shipment.json()["id"]
    assert shipment.json()["container"]["container_number"] == "MSCU1234566"

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


def test_container_check_digit_is_validated(client, operator_headers):
    response = client.post(
        "/shipments",
        headers=operator_headers,
        json={"origin": "Santos", "destination": "Roterdã", "container": {"container_number": "MSCU1234567"}},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Dígito verificador inválido. O correto para MSCU123456 é 6."


def test_reference_container_numbers_have_valid_check_digit():
    from app.services.container_number import container_check_digit, has_valid_check_digit

    assert container_check_digit("CSQU305438") == 3
    for number in ("CSQU3054383", "MSCU1234566", "MSCU7742121", "DKSU4829158", "TGHU7654320"):
        assert has_valid_check_digit(number), number
    assert not has_valid_check_digit("CSQU3054384")


def test_container_routes_validate_check_digit_and_format(client, operator_headers):
    shipment_id = client.post(
        "/shipments", headers=operator_headers, json={"origin": "Santos", "destination": "Roterdã"}
    ).json()["id"]

    for method, path in (("post", f"/shipments/{shipment_id}/containers"), ("put", f"/shipments/{shipment_id}/container")):
        wrong_digit = getattr(client, method)(path, headers=operator_headers, json={"container_number": "CSQU3054384"})
        assert wrong_digit.status_code == 422
        assert wrong_digit.json()["detail"] == "Dígito verificador inválido. O correto para CSQU305438 é 3."

        wrong_format = getattr(client, method)(path, headers=operator_headers, json={"container_number": "CSQ3054383"})
        assert wrong_format.status_code == 422
        assert wrong_format.json()["detail"].startswith("Número de contêiner inválido.")

    accepted = client.post(
        f"/shipments/{shipment_id}/containers", headers=operator_headers, json={"container_number": "csqu 305438-3"}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["container"]["container_number"] == "CSQU3054383"


def test_container_iso_code_is_always_set_by_the_server(client, operator_headers):
    shipment_id = client.post(
        "/shipments", headers=operator_headers, json={"origin": "Santos", "destination": "Roterdã"}
    ).json()["id"]

    for number, sent in (("CSQU3054383", "22G1"), ("TGHU7654320", ""), ("DKSU4829158", "x" * 500)):
        response = client.post(
            f"/shipments/{shipment_id}/containers",
            headers=operator_headers,
            json={"container_number": number, "iso_code": sent},
        )
        assert response.status_code == 200, (sent[:10], response.text)

    containers = client.get(f"/shipments/{shipment_id}", headers=operator_headers).json()["containers"]
    assert [item["iso_code"] for item in containers] == ["6346", "6346", "6346"]

    omitted = client.post(
        "/shipments",
        headers=operator_headers,
        json={"origin": "Santos", "destination": "Roterdã", "container": {"container_number": "MSCU7654329"}},
    )
    assert omitted.status_code == 201, omitted.text
    assert omitted.json()["container"]["iso_code"] == "6346"


def test_existing_container_iso_code_is_reset_to_standard(client, operator_headers, session_factory):
    from sqlalchemy import select

    from app.models import Container

    with session_factory() as db:
        db.add(Container(container_number="CSQU3054383", iso_code="OLD", status="AVAILABLE"))
        db.commit()

    shipment_id = client.post(
        "/shipments", headers=operator_headers, json={"origin": "Santos", "destination": "Roterdã"}
    ).json()["id"]
    response = client.put(
        f"/shipments/{shipment_id}/container",
        headers=operator_headers,
        json={"container_number": "CSQU3054383", "iso_code": "22G1"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["container"]["iso_code"] == "6346"
    with session_factory() as db:
        assert db.scalar(select(Container.iso_code).where(Container.container_number == "CSQU3054383")) == "6346"


def test_nonexistent_dates_are_rejected(client, operator_headers):
    for field in ("dispatched_at", "expected_arrival", "expected_return"):
        for value in ("2099-11-31T10:00:00Z", "2099-02-30T10:00:00Z", "2099-02-29T10:00:00Z", "2099-13-01T10:00:00Z", "abc"):
            response = client.post(
                "/shipments",
                headers=operator_headers,
                json={"origin": "Santos", "destination": "Roterdã", field: value},
            )
            assert response.status_code == 422, (field, value)
            error = response.json()["detail"][0]
            assert error["loc"][-1] == field
            assert error["msg"] == "Value error, Informe uma data válida."


def test_arrival_before_dispatch_and_return_before_arrival_are_rejected(client, operator_headers):
    arrival = client.post(
        "/shipments",
        headers=operator_headers,
        json={
            "origin": "Santos",
            "destination": "Roterdã",
            "dispatched_at": "2099-01-10T10:00:00Z",
            "expected_arrival": "2099-01-09T10:00:00Z",
        },
    )
    assert arrival.status_code == 422
    assert arrival.json()["detail"] == "Chegada prevista não pode ser anterior ao despacho"

    returned = client.post(
        "/shipments",
        headers=operator_headers,
        json={
            "origin": "Santos",
            "destination": "Roterdã",
            "expected_arrival": "2099-01-10T10:00:00Z",
            "expected_return": "2099-01-09T10:00:00Z",
        },
    )
    assert returned.status_code == 422
    assert returned.json()["detail"] == "Retorno previsto não pode ser anterior à chegada prevista"


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
        json={"container_number": "MSCU7742121"},
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
        json={"container_number": "MSCU7742121"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["detail"] == "Contêiner já está em trânsito em outro embarque"

    added = client.post(
        f"/shipments/{first_id}/containers",
        headers=operator_headers,
        json={"container_number": "MSCU7742137"},
    )
    assert added.status_code == 200, added.text
    body = added.json()
    assert body["container"]["container_number"] == "MSCU7742121"
    assert [item["container_number"] for item in body["containers"]] == ["MSCU7742121", "MSCU7742137"]

    repeated = client.post(
        f"/shipments/{first_id}/containers",
        headers=operator_headers,
        json={"container_number": "MSCU7742137"},
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
        json={"container_number": "MSCU7742121"},
    )
    assert reused.status_code == 200, reused.text

    replaced = client.put(
        f"/shipments/{first_id}/container",
        headers=operator_headers,
        json={"container_number": "MSCU7742142"},
    )
    assert replaced.status_code == 200, replaced.text
    replaced_body = replaced.json()
    assert replaced_body["container"]["container_number"] == "MSCU7742142"
    assert [item["container_number"] for item in replaced_body["containers"]] == [
        "MSCU7742121",
        "MSCU7742137",
        "MSCU7742142",
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
    from app.api.routes.dashboard import clear_dashboard_cache
    from app.models import Shipment

    with session_factory() as db:
        db.add(Shipment(origin="Santos", destination="Roterdã", status="REGISTERED"))
        db.add(Shipment(origin="Santos", destination="Roterdã", status="VALIDATED"))
        db.add(Shipment(origin="Santos", destination="Roterdã", status="PENDING_REVIEW"))
        db.commit()

    clear_dashboard_cache()
    body = client.get("/dashboard/metrics", headers=operator_headers).json()
    assert "shipments_in_yard" not in body
    assert "average_transit_hours" not in body
    assert body["efficiency_percent"] == 50.0
    assert len(body["volume_trend"]) == 30


PASSWORD_DETAIL = (
    "Senha deve ter no mínimo 8 caracteres, com maiúscula, minúscula, número e caractere especial."
)


def test_users_forbidden_for_operator_and_manager(client, operator_headers, manager_headers):
    payload = {"name": "Ana", "email": "ana@dockseal.com", "password": "Senha@123", "role": "OPERADOR"}
    for headers in (operator_headers, manager_headers):
        listed = client.get("/users", headers=headers)
        assert listed.status_code == 403
        assert listed.json()["detail"] == "Usuário sem permissão para esta ação"
        created = client.post("/users", headers=headers, json=payload)
        assert created.status_code == 403


def test_admin_user_crud_and_audit(client, admin_headers):
    created = client.post(
        "/users",
        headers=admin_headers,
        json={"name": "Ana", "email": " Ana@Dockseal.com ", "password": "Senha@123", "role": "OPERADOR"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["email"] == "ana@dockseal.com"
    assert body["status"] == "ACTIVE"
    assert body["role"]["name"] == "OPERADOR"
    assert "password_hash" not in body
    user_id = body["id"]

    listed = client.get("/users", headers=admin_headers)
    assert listed.status_code == 200
    assert any(user["id"] == user_id for user in listed.json())

    events = client.get("/events", headers=admin_headers).json()
    assert any(
        event["step"] == "USER_CREATED"
        and event["status"] == "SUCCESS"
        and event["shipment_id"] is None
        and event["observation"] == "Usuário ana@dockseal.com criado com o perfil OPERADOR."
        for event in events
    )

    weak = client.post(
        "/users",
        headers=admin_headers,
        json={"name": "Fraca", "email": "fraca@dockseal.com", "password": "senha123", "role": "OPERADOR"},
    )
    assert weak.status_code == 422
    assert weak.json()["detail"] == PASSWORD_DETAIL

    duplicate = client.post(
        "/users",
        headers=admin_headers,
        json={"name": "Ana 2", "email": "ana@dockseal.com", "password": "Senha@123", "role": "GESTOR"},
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["detail"] == "E-mail já cadastrado"

    patched = client.patch(f"/users/{user_id}", headers=admin_headers, json={"name": "Ana Souza"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "Ana Souza"
    events = client.get("/events", headers=admin_headers).json()
    assert any(
        event["step"] == "USER_UPDATED" and event["observation"] == "Usuário ana@dockseal.com atualizado."
        for event in events
    )

    me = client.get("/auth/me", headers=admin_headers).json()
    own = client.delete(f"/users/{me['id']}", headers=admin_headers)
    assert own.status_code == 422
    assert own.json()["detail"] == "Você não pode excluir o próprio usuário."

    demoted = client.patch(f"/users/{me['id']}", headers=admin_headers, json={"role": "GESTOR", "status": "INACTIVE"})
    assert demoted.status_code == 422
    assert demoted.json()["detail"] == "Não é possível alterar o perfil do último administrador."

    inactive = client.patch(f"/users/{me['id']}", headers=admin_headers, json={"status": "INACTIVE"})
    assert inactive.status_code == 422
    assert inactive.json()["detail"] == "Não é possível desativar o último administrador."

    second = client.post(
        "/users",
        headers=admin_headers,
        json={"name": "Admin 2", "email": "admin2@dockseal.com", "password": "Senha@123", "role": "ADMIN"},
    )
    assert second.status_code == 201
    deleted = client.delete(f"/users/{second.json()['id']}", headers=admin_headers)
    assert deleted.status_code == 204
    assert deleted.content == b""
    events = client.get("/events", headers=admin_headers).json()
    assert any(
        event["step"] == "USER_DELETED" and event["observation"] == "Usuário admin2@dockseal.com excluído."
        for event in events
    )

    missing = uuid.uuid4()
    not_found = client.patch(f"/users/{missing}", headers=admin_headers, json={"name": "Ninguém"})
    assert not_found.status_code == 404
    assert not_found.json()["detail"] == "Usuário não encontrado"
    assert client.delete(f"/users/{missing}", headers=admin_headers).status_code == 404


def _shipment_with_weight_divergence(client, operator_headers, custom_id: str) -> str:
    shipment = client.post(
        "/shipments",
        headers=operator_headers,
        json={"origin": "Santos", "destination": "Roterdã", "shipment_id_custom": custom_id},
    )
    assert shipment.status_code == 201, shipment.text
    shipment_id = shipment.json()["id"]
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
    return shipment_id


def test_treating_alerts_updates_shipment_review_status(client, operator_headers, manager_headers, session_factory):
    from app.models import Alert

    shipment_id = _shipment_with_weight_divergence(client, operator_headers, "SHP-STATUS-1")
    validation = client.post(f"/shipments/{shipment_id}/validate", headers=operator_headers)
    assert validation.status_code == 200, validation.text
    assert client.get(f"/shipments/{shipment_id}", headers=operator_headers).json()["status"] == "PENDING_REVIEW"

    with session_factory() as db:
        extra = Alert(
            field="lacre",
            severity="CRITICA",
            description="lacre: lacre divergente",
            status="OPEN",
            shipment_id=uuid.UUID(shipment_id),
        )
        db.add(extra)
        db.commit()
        extra_id = str(extra.id)

    alerts = client.get("/alerts", headers=manager_headers, params={"shipment_id": shipment_id}).json()
    weight = next(item for item in alerts if item["id"] != extra_id)
    resolved = client.patch(f"/alerts/{weight['id']}", headers=manager_headers, json={"status": "RESOLVED"})
    assert resolved.status_code == 200, resolved.text
    assert client.get(f"/shipments/{shipment_id}", headers=operator_headers).json()["status"] == "PENDING_REVIEW"

    closed = client.patch(f"/alerts/{extra_id}", headers=manager_headers, json={"status": "CLOSED"})
    assert closed.status_code == 200, closed.text
    assert client.get(f"/shipments/{shipment_id}", headers=operator_headers).json()["status"] == "VALIDATED"

    reopened = client.patch(f"/alerts/{weight['id']}", headers=manager_headers, json={"status": "OPEN"})
    assert reopened.status_code == 200, reopened.text
    detail = client.get(f"/shipments/{shipment_id}", headers=operator_headers).json()
    assert detail["status"] == "PENDING_REVIEW"


def test_reanalysis_updates_existing_alert_without_duplicating(
    client, operator_headers, manager_headers, session_factory
):
    from app.models import Alert

    shipment_id = _shipment_with_weight_divergence(client, operator_headers, "SHP-STATUS-2")
    with session_factory() as db:
        legacy = Alert(
            severity="MEDIA",
            description="Peso Bruto: texto antigo",
            status="OPEN",
            shipment_id=uuid.UUID(shipment_id),
        )
        gone = Alert(
            field="lacre",
            severity="ALTA",
            description="lacre: lacre antigo",
            status="OPEN",
            shipment_id=uuid.UUID(shipment_id),
        )
        db.add_all([legacy, gone])
        db.commit()
        legacy_id = str(legacy.id)
        gone_id = str(gone.id)

    validation = client.post(f"/shipments/{shipment_id}/validate", headers=operator_headers)
    assert validation.status_code == 200, validation.text
    alerts = client.get("/alerts", headers=manager_headers, params={"shipment_id": shipment_id}).json()
    assert {item["id"] for item in alerts} == {legacy_id, gone_id}
    updated = next(item for item in alerts if item["id"] == legacy_id)
    assert updated["status"] == "OPEN"
    assert updated["severity"] == "ALTA"
    assert updated["description"].startswith("peso bruto:")
    removed = next(item for item in alerts if item["id"] == gone_id)
    assert removed["status"] == "RESOLVED"
    assert removed["resolution_note"] == "Divergência não encontrada na nova análise."
    assert client.get(f"/shipments/{shipment_id}", headers=operator_headers).json()["status"] == "PENDING_REVIEW"

    dismissed = client.patch(
        f"/alerts/{legacy_id}",
        headers=manager_headers,
        json={"status": "DISMISSED", "resolution_note": "Falso positivo"},
    )
    assert dismissed.status_code == 200, dismissed.text
    assert client.get(f"/shipments/{shipment_id}", headers=operator_headers).json()["status"] == "VALIDATED"

    again = client.post(f"/shipments/{shipment_id}/validate", headers=operator_headers)
    assert again.status_code == 200, again.text
    alerts_again = client.get("/alerts", headers=manager_headers, params={"shipment_id": shipment_id}).json()
    assert len(alerts_again) == 2
    kept = next(item for item in alerts_again if item["id"] == legacy_id)
    assert kept["status"] == "DISMISSED"
    assert kept["resolution_note"] == "Falso positivo"
    assert kept["severity"] == "ALTA"
    assert client.get(f"/shipments/{shipment_id}", headers=operator_headers).json()["status"] == "VALIDATED"


def test_reanalysis_reuses_field_ignoring_unit_suffix(
    client, operator_headers, manager_headers, session_factory, analyzer
):
    from app.models import Alert

    shipment_id = _shipment_with_weight_divergence(client, operator_headers, "SHP-STATUS-3")
    with session_factory() as db:
        treated = Alert(
            field="Peso bruto (kg)",
            severity="MEDIA",
            description="Peso bruto (kg): texto antigo",
            status="DISMISSED",
            resolution_note="Falso positivo",
            shipment_id=uuid.UUID(shipment_id),
        )
        db.add(treated)
        db.commit()
        treated_id = str(treated.id)

    validation = client.post(f"/shipments/{shipment_id}/validate", headers=operator_headers)
    assert validation.status_code == 200, validation.text
    assert analyzer.known_fields == ["Peso bruto (kg)"]
    alerts = client.get("/alerts", headers=manager_headers, params={"shipment_id": shipment_id}).json()
    assert [item["id"] for item in alerts] == [treated_id]
    assert alerts[0]["status"] == "DISMISSED"
    assert alerts[0]["resolution_note"] == "Falso positivo"
    assert alerts[0]["severity"] == "ALTA"


def test_shipments_search_filters_by_custom_identifier(client, operator_headers):
    created = []
    for custom_id, destination in (
        ("SHP-FIND-1", "Roterdã"),
        ("SHP-FIND-1-extra", "Hamburgo"),
        ("SHP-OTHER-2", "Santos"),
        ("SHP-2026-0012", "Roterdã"),
        ("SHP-2026-0012-B", "Hamburgo"),
        ("SHP-2026-0013", "Santos"),
    ):
        response = client.post(
            "/shipments",
            headers=operator_headers,
            json={"origin": "Santos", "destination": destination, "shipment_id_custom": custom_id},
        )
        assert response.status_code == 201, response.text
        created.append(custom_id)

    prefix = client.get("/shipments", headers=operator_headers, params={"search": "SHP-FIND-1"}).json()
    assert sorted(item["shipment_id_custom"] for item in prefix) == ["SHP-FIND-1", "SHP-FIND-1-extra"]

    middle = client.get("/shipments", headers=operator_headers, params={"search": "find-1"}).json()
    assert middle == []

    pasted = client.get("/shipments", headers=operator_headers, params={"search": "SHP-2026-0012"}).json()
    assert sorted(item["shipment_id_custom"] for item in pasted) == ["SHP-2026-0012", "SHP-2026-0012-B"]
    assert "SHP-2026-0013" not in {item["shipment_id_custom"] for item in pasted}
    assert len(created) == 6


def test_delete_document_and_evidence(client, operator_headers, manager_headers, session_factory):
    import pytest
    from sqlalchemy import select

    from app.models import Document, Evidence
    from app.services.storage_service import read_file

    shipment = client.post(
        "/shipments",
        headers=operator_headers,
        json={"origin": "Santos", "destination": "Roterdã", "shipment_id_custom": "SHP-REPLACE-1"},
    )
    assert shipment.status_code == 201, shipment.text
    shipment_id = shipment.json()["id"]
    upload = client.post(
        f"/shipments/{shipment_id}/documents",
        headers=operator_headers,
        files=[
            ("files", ("bl.txt", b"Peso: 1 kg", "text/plain")),
            ("files", ("foto.txt", b"Lacre: SL-1", "text/plain")),
        ],
        data={"types": ["BILL_OF_LADING", "CONTAINER_PHOTO"]},
    )
    assert upload.status_code == 201, upload.text

    with session_factory() as db:
        document = db.scalar(select(Document).where(Document.shipment_id == uuid.UUID(shipment_id)))
        evidence = db.scalar(select(Evidence).where(Evidence.shipment_id == uuid.UUID(shipment_id)))
        assert document is not None and evidence is not None
        document_id = str(document.id)
        document_key = document.url
        evidence_id = str(evidence.id)
        evidence_key = evidence.url
        assert document.extraction is not None
        assert evidence.extraction is not None

    forbidden = client.delete(
        f"/shipments/{shipment_id}/documents/{document_id}",
        headers=manager_headers,
    )
    assert forbidden.status_code == 403

    deleted = client.delete(
        f"/shipments/{shipment_id}/documents/{document_id}",
        headers=operator_headers,
    )
    assert deleted.status_code == 204
    assert deleted.content == b""
    with pytest.raises(FileNotFoundError):
        read_file(document_key)

    detail = client.get(f"/shipments/{shipment_id}", headers=operator_headers).json()
    assert detail["documents"] == []
    assert [item["id"] for item in detail["evidences"]] == [evidence_id]

    removed_evidence = client.delete(
        f"/shipments/{shipment_id}/evidences/{evidence_id}",
        headers=operator_headers,
    )
    assert removed_evidence.status_code == 204
    with pytest.raises(FileNotFoundError):
        read_file(evidence_key)
    detail = client.get(f"/shipments/{shipment_id}", headers=operator_headers).json()
    assert detail["evidences"] == []

    missing = client.delete(
        f"/shipments/{shipment_id}/documents/{uuid.uuid4()}",
        headers=operator_headers,
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Documento não encontrado"

    empty = client.post(
        f"/shipments/{shipment_id}/documents",
        headers=operator_headers,
        files=[("files", ("vazio.txt", b"", "text/plain"))],
    )
    assert empty.status_code == 422
    assert "vazio" in empty.json()["detail"]

    events = client.get(f"/shipments/{shipment_id}/events", headers=manager_headers).json()
    assert [item["step"] for item in events[:2]] == ["EVIDENCE_DELETED", "DOCUMENT_DELETED"]


def test_review_status_keeps_pending_without_actionable_alert(session_factory):
    from app.models import Alert, Shipment, Validation
    from app.services.validation_service import sync_shipment_review_status

    with session_factory() as db:
        inconclusive = Shipment(origin="Santos", destination="Roterdã", status="PENDING_REVIEW")
        low_only = Shipment(origin="Santos", destination="Hamburgo", status="PENDING_REVIEW")
        db.add_all([inconclusive, low_only])
        db.flush()
        db.add(Validation(status="INCONCLUSIVO", details="Texto insuficiente", result={}, shipment_id=inconclusive.id))
        db.add(Validation(status="DIVERGENTE", details="Grafia", result={}, shipment_id=low_only.id))
        db.commit()

        sync_shipment_review_status(db, inconclusive)
        sync_shipment_review_status(db, low_only)
        assert inconclusive.status == "PENDING_REVIEW"
        assert low_only.status == "PENDING_REVIEW"

        db.add(
            Alert(
                field="grafia",
                severity="BAIXA",
                description="grafia: diferença de acento",
                status="RESOLVED",
                shipment_id=low_only.id,
            )
        )
        sync_shipment_review_status(db, low_only)
        assert low_only.status == "VALIDATED"

        db.add(
            Alert(
                field="peso bruto",
                severity="ALTA",
                description="peso: tratado",
                status="DISMISSED",
                shipment_id=inconclusive.id,
            )
        )
        sync_shipment_review_status(db, inconclusive)
        assert inconclusive.status == "VALIDATED"


def test_validate_new_password_rules():
    import pytest

    from app.core.security import validate_new_password

    with pytest.raises(ValueError):
        validate_new_password("senha123")
    validate_new_password("Password@123")
