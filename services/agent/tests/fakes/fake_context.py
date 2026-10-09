import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from fakes.jwt_check import subject

ROLES = ("orchestrator", "specialist")


@dataclass
class Conversation:
    salesperson_id: str
    turns: list[dict[str, Any]] = field(default_factory=list)
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FakeContext:
    """An in-memory context service that behaves like the contract, errors included."""

    conversations: dict[str, Conversation] = field(default_factory=dict)
    requests: list[tuple[str, str, str | None]] = field(default_factory=list)
    traceparents: list[str | None] = field(default_factory=list)
    failing: dict[str, int] = field(default_factory=dict)
    delay_s: float = 0.0

    def reset(self) -> None:
        self.conversations.clear()
        self.requests.clear()
        self.traceparents.clear()
        self.failing.clear()
        self.delay_s = 0.0

    def fact(self, conversation_id: str, key: str) -> dict[str, Any] | None:
        return self.conversations[conversation_id].facts.get(key)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def create_fake_context(state: FakeContext) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.api_route("/conversations", methods=["POST"])
    @app.api_route("/conversations/{conversation_id}/{rest:path}", methods=["GET", "POST", "PUT"])
    async def handle(
        request: Request, conversation_id: str | None = None, rest: str = ""
    ) -> JSONResponse:
        role = request.headers.get("x-agent-role")
        state.requests.append((request.method, request.url.path, role))
        state.traceparents.append(request.headers.get("traceparent"))
        await asyncio.sleep(state.delay_s)
        if request.method == "POST" and conversation_id is None and "create" in state.failing:
            return _error(
                state.failing["create"], "INTERNAL", "The request could not be completed."
            )
        kind = {"GET": "load", "PUT": "save", "POST": "save"}[request.method]
        if conversation_id is not None and kind in state.failing:
            return _error(state.failing[kind], "INTERNAL", "The request could not be completed.")

        caller = subject(request.headers)
        if caller is None:
            return _error(401, "UNAUTHENTICATED", "A valid bearer token is required.")
        if role not in ROLES:
            return _error(
                400, "INVALID_INPUT", "The X-Agent-Role header must be orchestrator or specialist."
            )

        if conversation_id is None:
            new_id = str(uuid.uuid4())
            state.conversations[new_id] = Conversation(caller[0])
            return JSONResponse(
                {"id": new_id, "salesperson_id": caller[0], "created_at": _now()}, status_code=201
            )

        conversation = state.conversations.get(conversation_id)
        if conversation is None:
            return _error(404, "NOT_FOUND", f"Conversation {conversation_id} was not found.")
        if conversation.salesperson_id != caller[0]:
            return _error(403, "FORBIDDEN", f"Conversation {conversation_id} is not yours.")
        return await route(request, conversation_id, conversation, rest, role)

    async def route(
        request: Request, cid: str, conversation: Conversation, rest: str, role: str | None
    ) -> JSONResponse:
        if request.method == "GET" and rest == "context":
            if request.query_params.get("agent") != role:
                return _error(
                    400, "INVALID_INPUT", "The agent parameter must match the X-Agent-Role header."
                )
            if role == "specialist":
                shown = conversation.facts.get("current_customer")
                return JSONResponse(
                    {
                        "conversation_id": cid,
                        "facts": {"current_customer": shown}
                        if shown and shown["value"] is not None
                        else {},
                    }
                )
            artifacts = [
                {k: a[k] for k in ("id", "type", "created_at")} for a in conversation.artifacts
            ]
            return JSONResponse(
                {
                    "conversation_id": cid,
                    "turns": conversation.turns[-10:],
                    "facts": conversation.facts,
                    "artifacts": artifacts,
                }
            )
        body = await request.json() if request.method != "GET" else {}
        if request.method == "POST" and rest == "turns":
            turn = {
                "id": str(uuid.uuid4()),
                "channel": body["channel"],
                "role": body["role"],
                "content": body["content"],
                "created_at": _now(),
            }
            conversation.turns.append(turn)
            return JSONResponse(
                {"id": turn["id"], "created_at": turn["created_at"]}, status_code=201
            )
        if request.method == "POST" and rest == "artifacts":
            artifact = {
                "id": str(uuid.uuid4()),
                "type": body["type"],
                "payload": body["payload"],
                "created_at": _now(),
            }
            conversation.artifacts.append(artifact)
            return JSONResponse({"id": artifact["id"]}, status_code=201)
        if request.method == "PUT" and rest.startswith("facts/"):
            if role != "orchestrator":
                return _error(403, "FORBIDDEN", "Only the orchestrator can write facts.")
            key = rest.removeprefix("facts/")
            expected = int(request.headers.get("if-match", "-1"))
            current = conversation.facts.get(key, {"version": 0})["version"]
            if expected != current:
                return _error(409, "CONFLICT", f"Fact {key} was changed by another request.")
            conversation.facts[key] = {"value": body["value"], "version": current + 1}
            return JSONResponse({"key": key, "value": body["value"], "version": current + 1})
        return _error(404, "NOT_FOUND", "The resource was not found.")

    return app
