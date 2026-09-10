"""Async MySQL person storage."""

import pytest
from app.db import persons
from app.errors import PersonAlreadyExistsError

from tests.conftest import TEST_TABLE, person


async def test_insert_and_read_back(clients, clean_stores):
    await persons.insert_person(clients.mysql, TEST_TABLE, person(-101, "alice"))
    found = await persons.get_person(clients.mysql, TEST_TABLE, -101)
    assert found is not None
    assert found.id == -101
    assert found.name == "alice"
    # The DATE column must come back as a date, not a string.
    assert found.birthdate == person(-101).birthdate


async def test_missing_person_is_none(clients, clean_stores):
    assert await persons.get_person(clients.mysql, TEST_TABLE, -999) is None


async def test_duplicate_id_raises_domain_error(clients, clean_stores):
    """
    The PRIMARY KEY is the source of truth for uniqueness.

    A duplicate makes execute() raise IntegrityError. It does not return a
    different row count, so a row-count check would never detect it.
    """
    await persons.insert_person(clients.mysql, TEST_TABLE, person(-102))
    with pytest.raises(PersonAlreadyExistsError):
        await persons.insert_person(clients.mysql, TEST_TABLE, person(-102))


async def test_delete_reports_whether_a_row_went(clients, clean_stores):
    await persons.insert_person(clients.mysql, TEST_TABLE, person(-103))
    assert await persons.delete_person(clients.mysql, TEST_TABLE, -103) is True
    assert await persons.delete_person(clients.mysql, TEST_TABLE, -103) is False


async def test_list_persons_pages(clients, clean_stores):
    for offset in range(3):
        await persons.insert_person(clients.mysql, TEST_TABLE, person(-110 - offset))
    items, total = await persons.list_persons(clients.mysql, TEST_TABLE, limit=2, offset=0)
    assert total == 3
    assert len(items) == 2

    rest, _ = await persons.list_persons(clients.mysql, TEST_TABLE, limit=2, offset=2)
    assert len(rest) == 1


@pytest.mark.parametrize("bad", ["person; DROP TABLE person", "person table", "1person", ""])
def test_safe_table_rejects_non_identifiers(bad):
    """A table name is interpolated, never bound, so it must be an identifier."""
    with pytest.raises(ValueError, match="unsafe table identifier"):
        persons.safe_table(bad)
