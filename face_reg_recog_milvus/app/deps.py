"""
Client lifecycle and FastAPI dependency providers.

The old design kept redis_conn / mysql_conn / milvus_collec_conn as module globals
guarded by a threading.Lock, with an ensure_connections() call at the top of every
function in case something had not been opened yet. That is a service locator:
untestable without monkeypatching module state, and easy to forget.

Here the clients are created once in the lifespan, stashed on app.state, and handed
to routes through Depends. A test can build the app with a different Clients object
and nothing has to be patched.
"""

import asyncio
import logging
from dataclasses import dataclass

import aiomysql
from fastapi import Depends, Request
from pymilvus import AsyncMilvusClient
from redis.asyncio import Redis

from app.config import (
    FACE_COLLECTION_NAME,
    FACE_INDEX_TYPE,
    FACE_METRIC_TYPE,
    FACE_VECTOR_DIM,
    MILVUS_HOST,
    MILVUS_PORT,
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_POOL_MAX,
    MYSQL_POOL_MIN,
    MYSQL_PORT,
    MYSQL_USER,
    REDIS_HOST,
    REDIS_PORT,
)
from app.db import vectors

logger = logging.getLogger("deps")


@dataclass
class Clients:
    """Every external connection the app holds, created once per process."""

    mysql: aiomysql.Pool
    redis: Redis
    milvus: AsyncMilvusClient


async def _retry(factory, label: str, attempts: int = 10, delay: float = 1.0, backoff: float = 1.5):
    """
    Retry an async factory with exponential backoff.

    Uses asyncio.sleep, not time.sleep: during startup the loop is already running,
    and a blocking sleep here would stall everything else trying to start.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await factory()
        except Exception as excep:  # noqa: BLE001 - startup retries are deliberately broad
            last = excep
            logger.warning("%s connection attempt %s/%s failed: %s", label, attempt, attempts, excep)
            await asyncio.sleep(delay)
            delay *= backoff
    raise RuntimeError(f"could not connect to {label} after {attempts} attempts") from last


async def _make_mysql() -> aiomysql.Pool:
    pool = await aiomysql.create_pool(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        db=MYSQL_DATABASE,
        minsize=MYSQL_POOL_MIN,
        maxsize=MYSQL_POOL_MAX,
        autocommit=False,
        # hand back a connection that has actually been checked, rather than one
        # that has been idle long enough for the server to have dropped it
        pool_recycle=3600,
    )
    async with pool.acquire() as conn, conn.cursor() as cur:
        await cur.execute("SELECT 1")
    return pool


async def _make_redis() -> Redis:
    client = Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    await client.ping()
    return client


async def _make_milvus() -> AsyncMilvusClient:
    client = AsyncMilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")
    await vectors.ensure_collection(
        client, FACE_COLLECTION_NAME, FACE_VECTOR_DIM, FACE_METRIC_TYPE, FACE_INDEX_TYPE
    )
    return client


async def create_clients() -> Clients:
    """Open every connection, retrying while dependencies are still coming up."""
    mysql = await _retry(_make_mysql, "mysql")
    redis = await _retry(_make_redis, "redis")
    milvus = await _retry(_make_milvus, "milvus")
    logger.info("all clients connected; milvus collection=%s", FACE_COLLECTION_NAME)
    return Clients(mysql=mysql, redis=redis, milvus=milvus)


async def close_clients(clients: Clients) -> None:
    """Shut everything down. Best-effort: one failure must not skip the others."""
    from app.services import triton

    try:
        clients.mysql.close()
        await clients.mysql.wait_closed()
    except Exception:
        logger.exception("error closing mysql pool")
    try:
        await clients.redis.aclose()
    except Exception:
        logger.exception("error closing redis")
    try:
        await clients.milvus.close()
    except Exception:
        logger.exception("error closing milvus")
    triton.close()


# --------------------------------------------------------------------- providers


def get_clients(request: Request) -> Clients:
    """The Clients object created during lifespan startup."""
    return request.app.state.clients


def get_mysql(clients: Clients = Depends(get_clients)) -> aiomysql.Pool:
    return clients.mysql


def get_redis(clients: Clients = Depends(get_clients)) -> Redis:
    return clients.redis


def get_milvus(clients: Clients = Depends(get_clients)) -> AsyncMilvusClient:
    return clients.milvus
