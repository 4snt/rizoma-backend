from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.database import init_db_pool, close_db_pool
from app.core.migrations import run_migrations
from app.core.elasticsearch import init_es_client, close_es_client
from app.api.v1 import projects, samples, jobs, analysis, worker, auth, admin, metagenomics
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(">>> RIZOMA API VERSION: 5 (Emergency Fix)", flush=True)
    await init_db_pool()
    await run_migrations()
    await init_es_client()
    yield
    await close_db_pool()
    await close_es_client()


app = FastAPI(
    title="Rizoma API",
    version="0.1.0",
    lifespan=lifespan,
)

_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
app.include_router(samples.router, prefix="/api/v1/samples", tags=["samples"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["jobs"])
app.include_router(analysis.router, prefix="/api/v1/analysis", tags=["analysis"])
app.include_router(worker.router, prefix="/api/v1/worker", tags=["worker"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(metagenomics.router, prefix="/api/v1/metagenomics", tags=["metagenomics"])


@app.get("/health")
async def health():
    return {"status": "ok"}
