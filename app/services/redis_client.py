"""Redis client factory and lifecycle for shared security state.

Rate-limit counters and JWT blacklist entries are stored in Redis
with TTL-based expiry. PostgreSQL remains the system of record.
"""

import logging
from typing import Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RedisUnavailable(Exception):
    """Raised when Redis is unreachable at startup or runtime."""


_redis_client: redis.Redis | None = None


async def create_redis_pool(redis_url: str, connect_timeout: int = 5) -> redis.Redis:
    """Create and verify the async Redis connection pool.

    Raises RedisUnavailable if the connection cannot be established.
    """
    client = redis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=connect_timeout,
    )
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        raise RedisUnavailable(
            f"Cannot connect to Redis at {redis_url}: {exc}"
        ) from exc

    logger.info("Redis connection pool created and verified")
    return client


def get_redis() -> redis.Redis:
    """Return the application's Redis client.

    Must only be called after the pool has been created during lifespan.
    """
    if _redis_client is None:
        raise RuntimeError("Redis pool not initialized. Call init_redis() first.")
    return _redis_client


def set_redis(client: redis.Redis) -> None:
    """Set the application's Redis client (called during lifespan startup)."""
    global _redis_client
    _redis_client = client


async def close_redis() -> None:
    """Close the Redis connection pool (called during lifespan shutdown)."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis connection pool closed")
