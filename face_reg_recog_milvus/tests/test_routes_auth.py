"""
Who may reach which route.

Three answers, and they must stay distinct: 401 means the caller is nobody, 403 means
the caller is known and not permitted, and anything else means they got through. The
tests below assert on the gate only -- a route that answers 404 or 422 has already
let the caller past, which is all that is being checked here.
"""

import pytest

from tests.conftest import FOREIGN_KEY, make_token

# Every route behind the gate, and the least role that opens it.
READS = [
    ("get", "/api/v1/persons"),
    ("get", "/api/v1/persons/1"),
    ("get", "/api/v1/persons/1/image"),
    ("post", "/api/v1/recognitions"),
]
WRITES = [
    ("post", "/api/v1/persons"),
    ("delete", "/api/v1/persons/1"),
]
PROTECTED = READS + WRITES


@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_no_token_is_rejected(anonymous, method, path):
    response = await getattr(anonymous, method)(path)
    assert response.status_code == 401
    assert response.json()["error"] == "AuthenticationError"


@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_a_token_signed_by_someone_else_is_rejected(anonymous, method, path):
    """
    The case that matters most: a well-formed token, with every claim this API wants,
    from an identity provider it does not trust.
    """
    forged = make_token(("face-admin",), key=FOREIGN_KEY)
    response = await getattr(anonymous, method)(path, headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_an_account_in_no_group_is_refused(stranger, method, path):
    """Authentication succeeded and authorization did not. 403, not 401."""
    response = await getattr(stranger, method)(path)
    assert response.status_code == 403
    assert response.json()["error"] == "AuthorizationError"


@pytest.mark.parametrize(("method", "path"), WRITES)
async def test_an_operator_may_not_change_the_population(operator, method, path):
    response = await getattr(operator, method)(path)
    assert response.status_code == 403


@pytest.mark.parametrize(("method", "path"), READS)
async def test_an_operator_gets_past_the_gate_on_reads(operator, method, path):
    assert (await getattr(operator, method)(path)).status_code not in (401, 403)


@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_an_admin_gets_past_the_gate_everywhere(client, method, path):
    assert (await getattr(client, method)(path)).status_code not in (401, 403)


@pytest.mark.parametrize("path", ["/health", "/health/ready", "/api/v1/auth/config"])
async def test_the_open_routes_stay_open(anonymous, path):
    """
    A load balancer probe cannot carry a token, and the browser has to read the login
    configuration before it can obtain one.
    """
    assert (await anonymous.get(path)).status_code == 200
