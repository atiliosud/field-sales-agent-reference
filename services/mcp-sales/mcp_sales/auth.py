import os
from collections.abc import Mapping
from dataclasses import dataclass

import jwt

from mcp_sales.errors import ToolFailure

ISSUER = "field-sales-demo"
REGIONS = ("North", "South")


@dataclass(frozen=True)
class Caller:
    id: str
    region: str


def authenticate(headers: Mapping[str, str]) -> Caller:
    scheme, _, token = headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ToolFailure("UNAUTHENTICATED", "A bearer token is required.")

    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise ToolFailure("UNAUTHENTICATED", "The token could not be validated.")

    try:
        claims = jwt.decode(
            token.strip(),
            secret,
            algorithms=["HS256"],
            issuer=ISSUER,
            options={"require": ["exp", "iss", "sub", "region"]},
        )
    except jwt.ExpiredSignatureError:
        raise ToolFailure("UNAUTHENTICATED", "The token has expired.") from None
    except jwt.InvalidTokenError:
        raise ToolFailure("UNAUTHENTICATED", "The token is not valid.") from None

    if claims["region"] not in REGIONS:
        raise ToolFailure("UNAUTHENTICATED", "The token is not valid.")
    return Caller(id=claims["sub"], region=claims["region"])
