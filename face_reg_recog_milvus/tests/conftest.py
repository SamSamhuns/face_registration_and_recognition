"""
Shared test fixtures.

The suite runs against live MySQL, Redis, Milvus and Triton services. It isolates
itself with two environment variables, which must be set BEFORE app.config is
imported, because config reads them at import time:

  MYSQL_CUR_TABLE      -> a throwaway SQL table
  FACE_COLLECTION_NAME -> a throwaway Milvus collection

Both stores must be redirected. If only SQL is redirected, the route tests write
face vectors into the production collection and leave them there.

No Authentik runs in the suite. It signs its own tokens with a key generated here,
and replaces app.security's key client with a stub that answers every key id with
the matching public key. Everything else about verification is the real code, so a
route test goes through the same signature, issuer, audience and group checks a real
request does.
"""

import os
import time
from datetime import date

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

TEST_TABLE = "test_person"
TEST_COLLECTION = "test_faces"
TEST_ISSUER = "https://authentik.test/application/o/face-api/"
TEST_CLIENT_ID = "face-api-test-client"
# The group names app.config defaults to. Spelled out rather than imported, so a
# change to either default breaks a test instead of silently changing what is tested.
ADMIN_GROUP = "face-admin"
OPERATOR_GROUP = "face-operator"
os.environ["MYSQL_CUR_TABLE"] = TEST_TABLE
os.environ["FACE_COLLECTION_NAME"] = TEST_COLLECTION
os.environ["OIDC_ISSUER"] = TEST_ISSUER
os.environ["OIDC_CLIENT_ID"] = TEST_CLIENT_ID

# ruff: noqa: E402 -- app.config reads the variables set above at import time.
from app import security
from app.config import FACE_COLLECTION_NAME, MYSQL_PERSON_TABLE
from app.schemas import PersonCreate
from app.server import app

FACES_DIR = "app/static/faces"

# --------------------------------------------------------------------- identity

SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
# A second key, for proving that a token signed by anybody else is refused.
FOREIGN_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StubJWKS:
    """Stands in for PyJWKClient. Answers every key id with the one test key."""

    key = SIGNING_KEY.public_key()

    def get_signing_key_from_jwt(self, _token):
        return self


# Replace the real client for the whole session. Nothing in the suite may reach out
# to an identity provider that is not there.
security._jwks = StubJWKS()


def make_token(groups: tuple[str, ...] = (), key=None, drop: tuple[str, ...] = (), **overrides) -> str:
    """
    A token as Authentik would issue one, signed with the suite's own key.

    `groups` sets the claim the route checks; `key` signs with a different key, and
    `drop` removes a claim, both for the tests that must be refused.
    """
    now = int(time.time())
    claims = {
        "iss": TEST_ISSUER,
        "aud": TEST_CLIENT_ID,
        "sub": "-".join(groups) or "no-groups",
        "preferred_username": "-".join(groups) or "nobody",
        "email": "tester@example.test",
        # An hour, not a minute: these are built once per session, and a slow suite
        # must not start failing because its own tokens went stale halfway through.
        "exp": now + 3600,
        "iat": now,
        "groups": list(groups),
    } | overrides
    for name in drop:
        claims.pop(name)
    return jwt.encode(claims, key or SIGNING_KEY, algorithm="RS256")


def signed_in(token: str) -> AsyncClient:
    """An HTTP client bound to the app, carrying `token` as a bearer."""
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


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
    """Signed in as an admin. Permitted on every route, so the feature tests use it."""
    async with signed_in(make_token((ADMIN_GROUP,))) as http_client:
        yield http_client


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def operator(clients):
    """Signed in as an operator: may identify a face, may not change the population."""
    async with signed_in(make_token((OPERATOR_GROUP,))) as http_client:
        yield http_client


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def stranger(clients):
    """
    A real Authentik account in no group at all.

    The interesting case: the token verifies perfectly, so this is authorization
    failing on its own rather than authentication failing first.
    """
    async with signed_in(make_token(())) as http_client:
        yield http_client


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def anonymous(clients):
    """No Authorization header at all, for checking that routes are closed."""
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
