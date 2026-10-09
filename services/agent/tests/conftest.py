from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from fakes.fake_context import FakeContext, create_fake_context
from fakes.fake_mcp import FakeMcp, create_fake_mcp
from fakes.fake_model import FakeChatModel
from fakes.servers import serve
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent_service.config import Settings
from agent_service.main import create_app

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
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(exporter))  # type: ignore[attr-defined]
    return exporter


@pytest.fixture(autouse=True)
def clear_spans(span_exporter: InMemorySpanExporter) -> None:
    span_exporter.clear()


@pytest.fixture(scope="session")
def mcp_state() -> FakeMcp:
    return FakeMcp()


@pytest.fixture(scope="session")
def mcp_url(mcp_state: FakeMcp) -> Iterator[str]:
    _, app = create_fake_mcp(mcp_state)
    with serve(app) as url:
        yield f"{url}/mcp"


@pytest.fixture(scope="session")
def context_state() -> FakeContext:
    return FakeContext()


@pytest.fixture(scope="session")
def context_url(context_state: FakeContext) -> Iterator[str]:
    with serve(create_fake_context(context_state)) as url:
        yield url


@pytest.fixture
def mcp(mcp_state: FakeMcp, mcp_url: str) -> FakeMcp:
    mcp_state.reset()
    return mcp_state


@pytest.fixture
def context(context_state: FakeContext, context_url: str) -> FakeContext:
    context_state.reset()
    return context_state


@pytest.fixture
def settings(mcp_url: str, context_url: str) -> Settings:
    return Settings(
        mcp_url=mcp_url,
        context_url=context_url,
        max_steps=6,
        tool_timeout_s=10,
        turn_timeout_s=60,
        prompt_orchestrator="orchestrator.v1",
        prompt_specialist="specialist.v1",
        azure_endpoint="",
        azure_api_key="",
        azure_deployment="",
        azure_api_version="",
    )


@pytest.fixture
def model() -> FakeChatModel:
    return FakeChatModel()


@pytest.fixture
def make_client(
    settings: Settings, model: FakeChatModel, mcp: FakeMcp, context: FakeContext
) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def make(**changes: Any) -> TestClient:
        config = Settings(**{**settings.__dict__, **changes})
        client = TestClient(create_app(config, model), raise_server_exceptions=False)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


@pytest.fixture
def make_token() -> Callable[..., str]:
    def make(
        sub: str = "sp-001", region: str = "North", expires_in: timedelta = timedelta(hours=1)
    ) -> str:
        claims = {
            "sub": sub,
            "name": "Test User",
            "region": region,
            "iss": "field-sales-demo",
            "exp": datetime.now(UTC) + expires_in,
        }
        return jwt.encode(claims, SECRET, algorithm="HS256")

    return make


@pytest.fixture
def token(make_token: Callable[..., str]) -> str:
    return make_token()


@pytest.fixture
def chat(client: TestClient, token: str) -> Callable[..., Any]:
    def send(
        message: str,
        conversation_id: str | None = None,
        confirm: bool = False,
        bearer: str | None = None,
    ) -> Any:
        body: dict[str, Any] = {"message": message, "confirm": confirm}
        if conversation_id:
            body["conversation_id"] = conversation_id
        return client.post(
            "/chat", json=body, headers={"Authorization": f"Bearer {bearer or token}"}
        )

    return send
