import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.modules.files.router import router as files_router
from app.modules.identity.router import router as identity_router
from app.modules.interop.router import router as interop_router
from app.modules.inventory.router import router as inventory_router
from app.modules.laboratory.router import router as lab_router
from app.modules.lims.router import router as lims_router
from app.modules.reports.router import router as reports_router
from app.shared.commit_middleware import CommitBeforeResponseMiddleware
from app.shared.db import dispose_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Migrations não rodam aqui. Quem manda no schema é o Alembic
    # (`alembic upgrade head`, no entrypoint do container). DDL no boot da app
    # foi exatamente o que produziu o "emergency schema repair" da versão anterior.
    yield
    await dispose_engine()


app = FastAPI(
    title="Rizoma API",
    version="2.0.0",
    description="Plataforma de biotecnologia ambiental — MVP (Fase 0 + Fatia 1).",
    lifespan=lifespan,
    # Em produção o proxy só encaminha /api/* pro backend — o resto cai no
    # frontend. Os caminhos default (/openapi.json, /docs, /redoc) ficam fora
    # dessa faixa e dão 404 atrás do proxy, então movem pra debaixo de /api.
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Commit da transação da requisição antes de a resposta sair — o teardown do
# `yield` em get_ctx roda depois do envio no FastAPI >= 0.118, o que deixava
# o cliente ver um 201 antes do commit (ver docstring do módulo).
app.add_middleware(CommitBeforeResponseMiddleware)

# Atenção: os routers não são uniformes. identity e lims expõem rotas relativas e
# recebem o prefixo aqui; files, laboratory e reports já declaram o próprio
# prefixo completo no APIRouter. Somar prefixo de novo produziria
# /api/v2/files/api/v2/files/...
app.include_router(identity_router, prefix="/api/v2/identity")
app.include_router(lims_router, prefix="/api/v2/lims")
app.include_router(inventory_router, prefix="/api/v2/inventory")
app.include_router(interop_router, prefix="/api/v2/interop")
app.include_router(files_router)
app.include_router(lab_router)
app.include_router(reports_router)


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok", "version": "2.0.0"}
