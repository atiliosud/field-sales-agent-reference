import asyncio
import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from mcp_sales import repository
from mcp_sales.server import app

SECRET = "test-secret-with-enough-length-for-hs256"


@pytest.fixture(scope="session", autouse=True)
def jwt_secret() -> Iterator[None]:
    patch = pytest.MonkeyPatch()
    patch.setenv("JWT_SECRET", SECRET)
    yield
    patch.undo()


@pytest.fixture(autouse=True)
def runtime_dir(tmp_path, monkeypatch) -> Any:
    monkeypatch.setattr(repository, "RUNTIME_DIR", tmp_path)
    return tmp_path


@pytest.fixture(scope="session")
def span_exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.fixture(autouse=True)
def clear_spans(span_exporter: InMemorySpanExporter) -> None:
    span_exporter.clear()


@pytest.fixture(scope="session")
def server_url() -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "server did not start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def make_token() -> Callable[..., str]:
    def make(
        sub: str = "sp-001",
        region: str = "North",
        expires_in: timedelta | None = timedelta(hours=1),
        issuer: str = "field-sales-demo",
        secret: str = SECRET,
    ) -> str:
        claims: dict[str, Any] = {"sub": sub, "name": "Test User", "region": region, "iss": issuer}
        if expires_in is not None:
            claims["exp"] = datetime.now(UTC) + expires_in
        return jwt.encode(claims, secret, algorithm="HS256")

    return make


@pytest.fixture
def call(server_url: str, make_token: Callable[..., str]) -> Callable[..., CallToolResult]:
    async def call_tool(
        name: str, arguments: dict[str, Any], headers: dict[str, str]
    ) -> CallToolResult:
        timeout = httpx.Timeout(30.0, read=60.0)
        async with (
            httpx.AsyncClient(headers=headers, timeout=timeout) as http_client,
            streamable_http_client(f"{server_url}/mcp", http_client=http_client) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            await session.initialize()
            return await session.call_tool(name, arguments)

    def call(
        name: str,
        arguments: dict[str, Any],
        token: str | None = "default",
        headers: dict[str, str] | None = None,
    ) -> CallToolResult:
        all_headers = dict(headers or {})
        if token == "default":
            token = make_token()
        if token is not None:
            all_headers["Authorization"] = f"Bearer {token}"
        return asyncio.run(call_tool(name, arguments, all_headers))

    return call


@pytest.fixture
def parse() -> Callable[[CallToolResult], dict[str, Any]]:
    def parse_text(result: CallToolResult) -> dict[str, Any]:
        assert len(result.content) == 1
        return json.loads(result.content[0].text)

    return parse_text
