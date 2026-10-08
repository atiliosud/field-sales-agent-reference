import os
from collections.abc import Mapping

import jwt


def subject(headers: Mapping[str, str]) -> tuple[str, str] | None:
    """The `sub` and `region` of a valid bearer token, as the real services check it."""
    scheme, _, token = headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    try:
        claims = jwt.decode(
            token.strip(),
            os.environ["JWT_SECRET"],
            algorithms=["HS256"],
            issuer="field-sales-demo",
            options={"require": ["exp", "iss", "sub", "region"]},
        )
    except jwt.InvalidTokenError:
        return None
    return claims["sub"], claims["region"]
