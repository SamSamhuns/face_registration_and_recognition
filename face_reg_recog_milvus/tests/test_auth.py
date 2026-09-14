"""Every /api/v1 route needs the API key. Health does not."""

import pytest

from tests.conftest import TEST_API_KEY

PROTECTED = [
    ("get", "/api/v1/persons"),
    ("get", "/api/v1/persons/1"),
    ("get", "/api/v1/persons/1/image"),
    ("delete", "/api/v1/persons/1"),
    ("post", "/api/v1/persons"),
    ("post", "/api/v1/recognitions"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_no_key_is_rejected(anonymous, method, path):
    response = await getattr(anonymous, method)(path)
    assert response.status_code == 401
    assert response.json()["error"] == "AuthenticationError"


@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_wrong_key_is_rejected(anonymous, method, path):
    response = await getattr(anonymous, method)(path, headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


async def test_right_key_gets_past_the_gate(anonymous):
    """401 must be gone. Anything else means the key was accepted."""
    response = await anonymous.get("/api/v1/persons", headers={"X-API-Key": TEST_API_KEY})
    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/health", "/health/ready"])
async def test_health_stays_open(anonymous, path):
    """A load balancer probe cannot carry a secret."""
    assert (await anonymous.get(path)).status_code == 200
