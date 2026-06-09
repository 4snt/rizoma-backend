import os
import logging
import asyncpg
from app.core.database import get_pool

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "migrations")

async def run_migrations():
    """
    Scans the migrations directory and executes any SQL files that haven't
    been applied yet. Tracks progress in a 'schema_migrations' table.
    """
    logger.info("Checking for pending database migrations...")
    pool = get_pool()
    
    async with pool.acquire() as conn:
        # Create the tracking table if it doesn't exist
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
        logger.info(f"Already applied migrations: {len(applied_set)}")
        
        # List all SQL files in the migrations directory
        if not os.path.exists(MIGRATIONS_DIR):
            logger.error(f"Migrations directory NOT FOUND: {os.path.abspath(MIGRATIONS_DIR)}")
            return
            
        files = sorted([f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql")])
        logger.info(f"Found {len(files)} migration files in {MIGRATIONS_DIR}")
        
        for filename in files:
            if filename in applied_set:
                logger.debug(f"Skipping already applied migration: {filename}")
                continue
                
            logger.info(f"Applying migration: {filename}")
            file_path = os.path.join(MIGRATIONS_DIR, filename)
            
            with open(file_path, "r") as f:
                sql = f.read()
            
            if not sql.strip():
                logger.warning(f"Migration file {filename} is empty, skipping.")
                continue
                
            # Execute the migration in a transaction
            async with conn.transaction():
                try:
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO schema_migrations (filename) VALUES ($1)",
                        filename
                    )
                    logger.info(f"Successfully applied {filename}")
                except Exception as e:
                    logger.error(f"FATAL: Error applying migration {filename}: {e}")
                    # Re-raise to stop startup if a migration fails
                    raise e

    logger.info("Database migrations check complete.")
