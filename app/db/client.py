import asyncpg
import logging
from app.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def create_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    logger.info("Database pool created")


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        logger.info("Database pool closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized — call create_pool() first")
    return _pool
