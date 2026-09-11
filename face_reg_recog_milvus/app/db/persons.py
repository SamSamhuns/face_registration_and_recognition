"""
Async MySQL access for person records, over an aiomysql pool.

A pool gives each task its own connection and takes it back afterwards. One shared
connection is not safe for concurrent use, because two overlapping requests would
interleave on the same socket.
"""

import logging
import re

import aiomysql

from app.errors import PersonAlreadyExistsError
from app.schemas import PersonCreate, PersonRead

logger = logging.getLogger("db.persons")

# Columns as declared by app/sql/init.sql.
COLUMNS = ("ID", "name", "birthdate", "country", "city", "title", "org")

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def safe_table(table: str) -> str:
    """
    Validate a table name for interpolation.

    SQL placeholders can only bind *values*, never identifiers, so a configurable
    table name has to be interpolated into the query string -- which means it must
    be proven to be a bare identifier first. Every actual value still goes through
    %s binding; this function is the narrow exception, not a licence to f-string
    the rest of the query.
    """
    if not _IDENTIFIER.match(table):
        raise ValueError(f"unsafe table identifier: {table!r}")
    return table


def row_to_person(row: dict) -> PersonRead:
    """init.sql spells the primary key `ID`; the public API spells it `id`."""
    return PersonRead(
        id=row["ID"],
        name=row["name"],
        birthdate=row["birthdate"],
        country=row["country"],
        city=row["city"] or "",
        title=row["title"] or "",
        org=row["org"] or "",
    )


async def get_person(pool: aiomysql.Pool, table: str, person_id: int) -> PersonRead | None:
    """Fetch one person, or None if there is no such row."""
    sql = f"SELECT * FROM {safe_table(table)} WHERE ID = %s"
    async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
        await cur.execute(sql, (person_id,))
        row = await cur.fetchone()
    return row_to_person(row) if row else None


async def list_persons(pool: aiomysql.Pool, table: str, limit: int, offset: int) -> tuple[list[PersonRead], int]:
    """Return one page of persons plus the total row count."""
    name = safe_table(table)
    async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
        await cur.execute(f"SELECT COUNT(*) AS n FROM {name}")
        total = (await cur.fetchone())["n"]
        await cur.execute(f"SELECT * FROM {name} ORDER BY ID LIMIT %s OFFSET %s", (limit, offset))
        rows = await cur.fetchall()
    return [row_to_person(r) for r in rows], total


async def insert_person(pool: aiomysql.Pool, table: str, person: PersonCreate) -> None:
    """
    Insert one person row and commit it.

    The PRIMARY KEY decides whether the id is a duplicate. A duplicate makes
    execute() raise IntegrityError; it does not return a different row count.
    """
    columns = ", ".join(COLUMNS)
    placeholders = ", ".join(["%s"] * len(COLUMNS))
    sql = f"INSERT INTO {safe_table(table)} ({columns}) VALUES ({placeholders})"
    values = (person.id, person.name, person.birthdate, person.country, person.city, person.title, person.org)

    async with pool.acquire() as conn, conn.cursor() as cur:
        try:
            await cur.execute(sql, values)
        except aiomysql.IntegrityError as excep:
            raise PersonAlreadyExistsError(f"person with id {person.id} already exists") from excep
        await conn.commit()

async def delete_person(pool: aiomysql.Pool, table: str, person_id: int) -> bool:
    """Delete one person. Returns False if there was no such row."""
    sql = f"DELETE FROM {safe_table(table)} WHERE ID = %s"
    async with pool.acquire() as conn, conn.cursor() as cur:
        affected = await cur.execute(sql, (person_id,))
        await conn.commit()
    return affected > 0


async def ping(pool: aiomysql.Pool) -> None:
    """Raise if MySQL is unreachable. Used by the readiness probe."""
    async with pool.acquire() as conn, conn.cursor() as cur:
        await cur.execute("SELECT 1")
