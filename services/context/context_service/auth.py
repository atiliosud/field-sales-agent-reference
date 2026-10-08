import os
from dataclasses import dataclass

import jwt
from fastapi import Header

from context_service import telemetry
from context_service.errors import unauthenticated

ISSUER = "field-sales-demo"
REGIONS = ("North", "South")


@dataclass(frozen=True)
class Caller:
    id: str
    region: str


def authenticated(authorization: str | None = Header(default=None)) -> Caller:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthenticated("A bearer token is required.")

    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise unauthenticated("The token could not be validated.")

    try:
        claims = jwt.decode(
            token.strip(),
            secret,
            algorithms=["HS256"],
            issuer=ISSUER,
            options={"require": ["exp", "iss", "sub", "region"]},
        )
    except jwt.ExpiredSignatureError:
        raise unauthenticated("The token has expired.") from None
    except jwt.InvalidTokenError:
        raise unauthenticated("The token is not valid.") from None

    if claims["region"] not in REGIONS:
        raise unauthenticated("The token is not valid.")
    telemetry.set_attribute("user.id", claims["sub"])
    return Caller(id=claims["sub"], region=claims["region"])
