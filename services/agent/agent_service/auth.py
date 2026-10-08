import os
from dataclasses import dataclass

import jwt
from fastapi import Header

from agent_service.errors import ApiError

ISSUER = "field-sales-demo"
REGIONS = ("North", "South")


@dataclass(frozen=True)
class Caller:
    id: str
    region: str
    token: str


def _unauthenticated(message: str) -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", message)


def authenticated(authorization: str | None = Header(default=None)) -> Caller:
    scheme, _, token = (authorization or "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise _unauthenticated("A bearer token is required.")

    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise _unauthenticated("The token could not be validated.")

    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=ISSUER,
            options={"require": ["exp", "iss", "sub", "region"]},
        )
    except jwt.ExpiredSignatureError:
        raise _unauthenticated("The token has expired.") from None
    except jwt.InvalidTokenError:
        raise _unauthenticated("The token is not valid.") from None

    if claims["region"] not in REGIONS:
        raise _unauthenticated("The token is not valid.")
    return Caller(id=claims["sub"], region=claims["region"], token=token)
