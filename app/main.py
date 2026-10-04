from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import alerts, analysis, auth, shipments
from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine
from app.services.auth_service import seed_roles

DESCRIPTION = """
API da **Dockseal — Plataforma Inteligente de Conformidade Portuária**.

**Como autenticar:** faça `POST /auth/login` (ou clique em **Authorize**) e envie o token em
todas as requisições no cabeçalho `Authorization: Bearer <token>`.

Guia completo para o front-end: `docs/API.md` no repositório.
"""

TAGS = [
    {"name": "Autenticação", "description": "Login e dados do usuário logado."},
    {"name": "Análise de documentos", "description": "Agente de IA que compara documentos e aponta divergências."},
    {"name": "Embarques", "description": "Cadastro de embarques, contêineres, documentos e validação com IA."},
    {"name": "Alertas e histórico", "description": "Alertas gerados pelas validações e trilha de auditoria."},
    {"name": "Infra", "description": "Verificação de saúde da API."},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_roles(db)
    yield


app = FastAPI(
    title=get_settings().app_name,
    description=DESCRIPTION,
    openapi_tags=TAGS,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(shipments.router)
app.include_router(alerts.router)


@app.get("/health", tags=["Infra"], summary="Verificar se a API está no ar")
def health():
    return {"status": "ok"}
