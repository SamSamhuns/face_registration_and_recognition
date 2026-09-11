"""Redis read cache. The point of these tests is that types survive the round trip."""

from app.db import cache, persons

from tests.conftest import TEST_TABLE, person


async def test_cache_round_trip_keeps_types(clients, clean_stores):
    """
    A cache hit and a database hit must be indistinguishable.

    A redis hash would make every value a string, so a cached read would give the id
    as "-201" while a database read gives -201. JSON goes through the model, so the
    types stay correct.
    """
    original = person(-201, "cached")
    await persons.insert_person(clients.mysql, TEST_TABLE, original)
    from_db = await persons.get_person(clients.mysql, TEST_TABLE, -201)

    await cache.set_person(clients.redis, TEST_TABLE, from_db, ttl=60)
    from_cache = await cache.get_person(clients.redis, TEST_TABLE, -201)

    assert from_cache == from_db
    assert isinstance(from_cache.id, int)
    assert from_cache.birthdate == original.birthdate


async def test_miss_returns_none(clients, clean_stores):
    assert await cache.get_person(clients.redis, TEST_TABLE, -999) is None


async def test_invalidate_removes_the_entry(clients, clean_stores):
    await persons.insert_person(clients.mysql, TEST_TABLE, person(-202))
    stored = await persons.get_person(clients.mysql, TEST_TABLE, -202)
    await cache.set_person(clients.redis, TEST_TABLE, stored, ttl=60)

    await cache.invalidate(clients.redis, TEST_TABLE, -202)
    assert await cache.get_person(clients.redis, TEST_TABLE, -202) is None


async def test_unreadable_entry_is_treated_as_a_miss(clients, clean_stores):
    """An entry written by an older schema must not break the read path."""
    await clients.redis.set(f"{TEST_TABLE}_-203", "not json")
    assert await cache.get_person(clients.redis, TEST_TABLE, -203) is None
