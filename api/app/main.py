import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.modules.files.router import router as files_router
from app.modules.identity.router import router as identity_router
from app.modules.interop.router import router as interop_router
from app.modules.inventory.router import router as inventory_router
from app.modules.jobs.reaper import reaper_loop
from app.modules.jobs.router import router as jobs_router
from app.modules.laboratory.router import router as lab_router
from app.modules.lims.router import router as lims_router
from app.modules.reports.router import router as reports_router
from app.shared.db import dispose_engine

# Os routers de app/api/v1/ NÃO são montados. Eles falam com o schema anterior
# (samples.fastq_r1_oid, projects sem organization_id) que o baseline do Alembic
# substituiu. Continuam no repositório como referência; mounta-los agora só
# produziria erro 500. Serão removidos quando a v2 cobrir o que falta.

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Migrations não rodam aqui. Quem manda no schema é o Alembic
    # (`alembic upgrade head`, no entrypoint do container). DDL no boot da app
    # foi exatamente o que produziu o "emergency schema repair" da versão anterior.
    reaper = asyncio.create_task(reaper_loop())
    yield
    reaper.cancel()
    try:
        await reaper
    except asyncio.CancelledError:
        pass
    await dispose_engine()


app = FastAPI(
    title="Rizoma API",
    version="2.0.0",
    description="Plataforma de biotecnologia ambiental — MVP (Fase 0 + Fatia 1).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Atenção: os routers não são uniformes. identity e lims expõem rotas relativas e
# recebem o prefixo aqui; files, jobs, laboratory e reports já declaram o próprio
# prefixo completo no APIRouter. Somar prefixo de novo produziria
# /api/v2/files/api/v2/files/...
app.include_router(identity_router, prefix="/api/v2/identity")
app.include_router(lims_router, prefix="/api/v2/lims")
app.include_router(inventory_router, prefix="/api/v2/inventory")
app.include_router(interop_router, prefix="/api/v2/interop")
app.include_router(files_router)
app.include_router(jobs_router)
app.include_router(lab_router)
app.include_router(reports_router)


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok", "version": "2.0.0"}
