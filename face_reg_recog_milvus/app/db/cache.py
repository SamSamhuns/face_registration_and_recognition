"""
Async Redis read-cache for person records.

Records are stored as JSON, not as a redis hash. A hash makes every value a string,
so a cached read would give {"id": "7001", "birthdate": "1990-01-01"} while a
database read gives an int and a date. JSON goes through the Pydantic model in both
directions, so a hit and a miss look the same to the caller.
"""

import logging

from redis.asyncio import Redis

from app.schemas import PersonRead

logger = logging.getLogger("db.cache")


def _key(table: str, person_id: int) -> str:
    return f"{table}_{person_id}"


async def get_person(redis: Redis, table: str, person_id: int) -> PersonRead | None:
    """Return the cached person, or None on a miss. Never raises on bad cache data."""
    raw = await redis.get(_key(table, person_id))
    if not raw:
        return None
    try:
        return PersonRead.model_validate_json(raw)
    except ValueError:
        # A cache entry written by an older schema is a miss, not an error.
        logger.warning("discarding unreadable cache entry for %s", _key(table, person_id))
        await redis.delete(_key(table, person_id))
        return None


async def set_person(redis: Redis, table: str, person: PersonRead, ttl: int) -> None:
    """Cache a person for `ttl` seconds."""
    await redis.set(_key(table, person.id), person.model_dump_json(), ex=ttl)


async def invalidate(redis: Redis, table: str, person_id: int) -> None:
    """Drop a person from the cache."""
    await redis.delete(_key(table, person_id))


async def ping(redis: Redis) -> None:
    """Raise if Redis is unreachable. Used by the readiness probe."""
    await redis.ping()
