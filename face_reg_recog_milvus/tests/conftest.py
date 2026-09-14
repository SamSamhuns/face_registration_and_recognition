"""
Shared test fixtures.

The suite runs against live MySQL, Redis, Milvus and Triton services. It isolates
itself with two environment variables, which must be set BEFORE app.config is
imported, because config reads them at import time:

  MYSQL_CUR_TABLE      -> a throwaway SQL table
  FACE_COLLECTION_NAME -> a throwaway Milvus collection

Both stores must be redirected. If only SQL is redirected, the route tests write
face vectors into the production collection and leave them there.
"""

import os
from datetime import date

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

TEST_TABLE = "test_person"
TEST_COLLECTION = "test_faces"
TEST_API_KEY = "test-key-not-a-secret"
os.environ["MYSQL_CUR_TABLE"] = TEST_TABLE
os.environ["FACE_COLLECTION_NAME"] = TEST_COLLECTION
os.environ["API_KEY"] = TEST_API_KEY

# ruff: noqa: E402 -- app.config reads the variables set above at import time.
from app.config import FACE_COLLECTION_NAME, MYSQL_PERSON_TABLE
from app.schemas import PersonCreate
from app.server import app

FACES_DIR = "app/static/faces"


def person(person_id: int, name: str = "test person") -> PersonCreate:
    """Build a valid PersonCreate with the given id."""
    return PersonCreate(
        id=person_id,
        name=name,
        birthdate=date(1990, 1, 30),
        country="NP",
        city="KTM",
        title="tester",
        org="qa",
    )


def form_fields(new_person: PersonCreate) -> dict[str, str]:
    """PersonCreate as flat multipart form fields, as the API expects them."""
    return {
        "id": str(new_person.id),
        "name": new_person.name,
        "birthdate": new_person.birthdate.isoformat(),
        "country": new_person.country,
        "city": new_person.city,
        "title": new_person.title,
        "org": new_person.org,
    }


def read_face(name: str) -> bytes:
    with open(f"{FACES_DIR}/{name}", "rb") as fptr:
        return fptr.read()


@pytest.fixture(scope="session")
def one_face() -> bytes:
    return read_face("one_face_1.jpg")


@pytest.fixture(scope="session")
def other_face() -> bytes:
    return read_face("one_face_2.jpg")


@pytest.fixture(scope="session")
def no_face() -> bytes:
    return read_face("no_face.jpg")


@pytest.fixture(scope="session")
def two_faces() -> bytes:
    return read_face("two_faces.jpg")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def clients():
    """
    Start the app lifespan once for the whole session and expose its clients.

    `app.router.lifespan_context` runs the same startup the real server runs, so
    the tests exercise the actual connection setup. ASGITransport alone does NOT
    run lifespan, so without this the app state would be empty.
    """
    async with app.router.lifespan_context(app):
        pool = app.state.clients.mysql
        # Create the throwaway table with the production schema, then empty it.
        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(f"CREATE TABLE IF NOT EXISTS {TEST_TABLE} LIKE {MYSQL_PERSON_TABLE}")
            await cur.execute(f"DELETE FROM {TEST_TABLE}")
            await conn.commit()

        yield app.state.clients

        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(f"DROP TABLE IF EXISTS {TEST_TABLE}")
            await conn.commit()
        await app.state.clients.milvus.drop_collection(FACE_COLLECTION_NAME)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client(clients):
    """An HTTP client bound to the running app, carrying the API key."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": TEST_API_KEY},
    ) as http_client:
        yield http_client


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def anonymous(clients):
    """A client with no API key, for checking that routes are closed."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client:
        yield http_client


@pytest_asyncio.fixture(loop_scope="session")
async def clean_stores(clients):
    """Empty both stores before and after a test, so tests do not affect each other."""

    async def purge():
        async with clients.mysql.acquire() as conn, conn.cursor() as cur:
            await cur.execute(f"DELETE FROM {TEST_TABLE}")
            await conn.commit()
        await clients.milvus.delete(collection_name=FACE_COLLECTION_NAME, filter="person_id != 0")
        for key in await clients.redis.keys(f"{TEST_TABLE}_*"):
            await clients.redis.delete(key)

    await purge()
    yield
    await purge()
