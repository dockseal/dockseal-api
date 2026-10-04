import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.agents.compliance_agent import get_analyzer
from app.core.database import Base, get_db
from app.schemas.analysis import (
    AnalysisResult,
    AnalysisStatus,
    AnalyzedDocument,
    Divergence,
    FieldOccurrence,
    Severity,
    SourceDocument,
)
from app.services.auth_service import AuthenticationService, seed_roles


class FakeAnalyzer:
    """Simula o agente: aponta divergência de peso quando os textos citam pesos diferentes."""

    def __init__(self):
        self.received: list[SourceDocument] = []

    async def analyze(self, documents: list[SourceDocument]) -> AnalysisResult:
        self.received = documents
        weights = {d.name: d.text.split("Peso:")[1].split()[0] for d in documents if "Peso:" in d.text}
        divergent = len(set(weights.values())) > 1
        divergences = []
        if divergent:
            divergences.append(
                Divergence(
                    field="peso bruto",
                    description="Pesos diferentes entre os documentos.",
                    occurrences=[FieldOccurrence(document=n, value=w) for n, w in weights.items()],
                    severity=Severity.ALTA,
                    suggestion="Corrigir o peso para o valor do Bill of Lading.",
                    document_to_fix=list(weights)[-1],
                    confidence=0.95,
                )
            )
        return AnalysisResult(
            status=AnalysisStatus.DIVERGENTE if divergent else AnalysisStatus.CONFORME,
            summary="Análise simulada",
            documents=[AnalyzedDocument(document=d.name, identified_type="OUTRO") for d in documents],
            divergences=divergences,
            confidence=0.9,
        )


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(main_module, "SessionLocal", factory)
    with factory() as db:
        seed_roles(db)
        auth = AuthenticationService(db)
        auth.create_user("Operador", "operador@dockseal.com", "senha123", "OPERADOR")
        auth.create_user("Gestor", "gestor@dockseal.com", "senha123", "GESTOR")
    return factory


@pytest.fixture
def analyzer():
    return FakeAnalyzer()


@pytest.fixture
def client(session_factory, analyzer, tmp_path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "upload_dir", tmp_path)

    def override_db():
        with session_factory() as db:
            yield db

    main_module.app.dependency_overrides[get_db] = override_db
    main_module.app.dependency_overrides[get_analyzer] = lambda: analyzer
    with TestClient(main_module.app) as c:
        yield c
    main_module.app.dependency_overrides.clear()


def login(client, email: str) -> dict:
    response = client.post("/auth/login", data={"username": email, "password": "senha123"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def operator_headers(client):
    return login(client, "operador@dockseal.com")


@pytest.fixture
def manager_headers(client):
    return login(client, "gestor@dockseal.com")
