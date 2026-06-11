import asyncpg
from app.core.config import settings

_pool: asyncpg.Pool | None = None


async def init_db_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.postgres_dsn_raw,
        min_size=2,
        max_size=10,
    )
    # Emergency repair: ensure critical columns exist before the app starts fully.
    # This is a fail-safe for the migration runner.
    try:
        async with _pool.acquire() as conn:
            print(">>> [database] Running emergency schema repair...", flush=True)
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT;")
            await conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';")
            await conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL;")
            await conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS bioproject_accession VARCHAR(20);")
            await conn.execute("ALTER TABLE samples DROP COLUMN IF EXISTS fastq_r1_key_old;")
            await conn.execute("ALTER TABLE samples DROP COLUMN IF EXISTS fastq_r2_key_old;")
            print(">>> [database] Emergency repair complete.", flush=True)
    except Exception as e:
        print(f"!!! [database] Emergency repair failed (this might be normal if columns exist): {e}", flush=True)


async def close_db_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized")
    return _pool
