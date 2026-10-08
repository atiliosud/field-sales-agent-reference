from datetime import UTC, datetime, timedelta

import jwt
import pytest

import make_token

SECRET = "test-secret-with-enough-length-for-hs256"


@pytest.mark.parametrize(
    ("salesperson_id", "name", "region"),
    [("sp-001", "Ingrid Larsen", "North"), ("sp-002", "Mateo Alvarez", "South")],
)
def test_token_decodes_with_the_contract_claims(salesperson_id, name, region):
    token = make_token.make_token(salesperson_id, SECRET)

    claims = jwt.decode(
        token,
        SECRET,
        algorithms=["HS256"],
        issuer="field-sales-demo",
        options={"require": ["sub", "name", "region", "iss", "exp"]},
    )

    assert (claims["sub"], claims["name"], claims["region"]) == (salesperson_id, name, region)


def test_token_expires_in_eight_hours():
    token = make_token.make_token("sp-001", SECRET)

    exp = jwt.decode(token, SECRET, algorithms=["HS256"], issuer="field-sales-demo")["exp"]
    expected = datetime.now(UTC) + timedelta(hours=8)

    assert abs(datetime.fromtimestamp(exp, UTC) - expected) < timedelta(minutes=1)


def test_secret_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)

    assert make_token.read_secret() == SECRET
