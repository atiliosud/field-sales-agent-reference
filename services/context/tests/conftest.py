import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from context_service.db import migrate
from context_service.main import create_app

SECRET = "test-secret-with-enough-length-for-hs256"


@pytest.fixture(scope="session", autouse=True)
def jwt_secret() -> Iterator[None]:
    patch = pytest.MonkeyPatch()
    patch.setenv("JWT_SECRET", SECRET)
    yield
    patch.undo()


@pytest.fixture(scope="session")
def span_exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.fixture(autouse=True)
def clear_spans(span_exporter: InMemorySpanExporter) -> None:
    span_exporter.clear()


@pytest.fixture(scope="session")
def migrated_database(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("template") / "context.db"
    migrate(f"sqlite+aiosqlite:///{path}")
    return path


@pytest.fixture
def client(tmp_path, monkeypatch, migrated_database) -> Iterator[TestClient]:
    database = tmp_path / "context.db"
    shutil.copy(migrated_database, database)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database}")
    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def make_token() -> Callable[..., str]:
    def make(
        sub: str = "sp-001",
        region: str = "North",
        expires_in: timedelta | None = timedelta(hours=1),
        secret: str = SECRET,
    ) -> str:
        claims: dict[str, Any] = {
            "sub": sub,
            "name": "Test User",
            "region": region,
            "iss": "field-sales-demo",
        }
        if expires_in is not None:
            claims["exp"] = datetime.now(UTC) + expires_in
        return jwt.encode(claims, secret, algorithm="HS256")

    return make


@pytest.fixture
def headers(make_token: Callable[..., str]) -> Callable[..., dict[str, str]]:
    def build(role: str = "orchestrator", sub: str = "sp-001", **extra: str) -> dict[str, str]:
        token = make_token(sub=sub, region="North" if sub == "sp-001" else "South")
        return {"Authorization": f"Bearer {token}", "X-Agent-Role": role, **extra}

    return build


@pytest.fixture
def conversation(client: TestClient, headers: Callable[..., dict[str, str]]) -> str:
    response = client.post("/conversations", headers=headers())
    assert response.status_code == 201
    return response.json()["id"]
