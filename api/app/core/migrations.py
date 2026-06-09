import os
import sys
import logging
import asyncpg
from app.core.database import get_pool

logger = logging.getLogger(__name__)

# Use absolute path to avoid ambiguity in container
MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")

async def run_migrations():
    """
    Scans the migrations directory and executes any SQL files that haven't
    been applied yet. Tracks progress in a 'schema_migrations' table.
    """
    print(f">>> [migrations] Starting migrations check. Directory: {MIGRATIONS_DIR}", flush=True)
    
    if not os.path.exists(MIGRATIONS_DIR):
        print(f"!!! [migrations] ERROR: Migrations directory NOT FOUND at {os.path.abspath(MIGRATIONS_DIR)}", flush=True)
        return

    pool = get_pool()
    
    try:
        async with pool.acquire() as conn:
            # Create the tracking table if it doesn't exist
            print(">>> [migrations] Ensuring schema_migrations table exists...", flush=True)
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            
            # Get list of applied migrations
            applied = await conn.fetch("SELECT filename FROM schema_migrations")
            applied_set = {r["filename"] for r in applied}
            print(f">>> [migrations] Already applied: {len(applied_set)} migrations.", flush=True)
            
            files = sorted([f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql")])
            print(f">>> [migrations] Found {len(files)} SQL files in directory.", flush=True)
            
            for filename in files:
                if filename in applied_set:
                    continue
                    
                print(f">>> [migrations] Applying: {filename}", flush=True)
                file_path = os.path.join(MIGRATIONS_DIR, filename)
                
                with open(file_path, "r") as f:
                    sql = f.read()
                
                if not sql.strip():
                    continue
                    
                # Execute the migration in a transaction
                async with conn.transaction():
                    try:
                        await conn.execute(sql)
                        await conn.execute(
                            "INSERT INTO schema_migrations (filename) VALUES ($1)",
                            filename
                        )
                        print(f">>> [migrations] SUCCESS: {filename}", flush=True)
                    except Exception as e:
                        print(f"!!! [migrations] FATAL ERROR in {filename}: {e}", flush=True)
                        raise e

        print(">>> [migrations] All migrations checked and applied.", flush=True)
    except Exception as e:
        print(f"!!! [migrations] FATAL: Unexpected error during migration process: {e}", flush=True)
        raise e
