"""Print a demo JWT (HS256) for a salesperson. Demo only."""

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt

ROOT = Path(__file__).resolve().parent.parent
ISSUER = "field-sales-demo"
LIFETIME = timedelta(hours=8)


def load_salespeople() -> dict[str, dict[str, str]]:
    path = ROOT / "mock-data" / "salespeople.json"
    return {person["id"]: person for person in json.loads(path.read_text(encoding="utf-8"))}


def read_secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if secret:
        return secret
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "JWT_SECRET" and value.strip():
                return value.strip()
    raise SystemExit("JWT_SECRET is not set in the environment or in .env")


def make_token(salesperson_id: str, secret: str) -> str:
    person = load_salespeople()[salesperson_id]
    claims = {
        "sub": person["id"],
        "name": person["name"],
        "region": person["region"],
        "iss": ISSUER,
        "exp": datetime.now(UTC) + LIFETIME,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("salesperson_id", choices=sorted(load_salespeople()))
    args = parser.parse_args()
    print(make_token(args.salesperson_id, read_secret()))


if __name__ == "__main__":
    main()
