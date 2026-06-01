from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.database import init_db_pool, close_db_pool
from app.core.elasticsearch import init_es_client, close_es_client
from app.core.minio import ensure_buckets
from app.api.v1 import projects, samples, jobs, analysis, worker, auth, admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db_pool()
    await init_es_client()
    ensure_buckets()
    yield
    await close_db_pool()
    await close_es_client()


app = FastAPI(
    title="Bio-Platform API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
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


@app.get("/health")
async def health():
    return {"status": "ok"}
