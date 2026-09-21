"""
verify_token is the only thing between a forged token and the API, so it is checked
against tokens minted here.

This file is about the token itself. Who may reach which route is test_routes_auth.
"""

import jwt
import pytest
from app import security

from tests.conftest import FOREIGN_KEY, make_token


def test_a_good_token_gives_back_its_claims():
    claims = security.verify_token(make_token(("face-operator",)))
    assert claims["sub"] == "face-operator"
    assert claims["groups"] == ["face-operator"]


@pytest.mark.parametrize(
    ("reason", "kwargs"),
    [
        ("expired", {"exp": 1}),
        ("issued by a different identity provider", {"iss": "https://elsewhere/"}),
        ("meant for another application on the same authentik", {"aud": "other-client"}),
        ("signed with a key that is not authentik's", {"key": FOREIGN_KEY}),
        ("carries no expiry at all", {"drop": ("exp",)}),
        ("carries no subject", {"drop": ("sub",)}),
        ("carries no audience", {"drop": ("aud",)}),
    ],
)
def test_a_bad_token_is_refused(reason, kwargs):
    with pytest.raises(jwt.PyJWTError):
        security.verify_token(make_token(**kwargs))
