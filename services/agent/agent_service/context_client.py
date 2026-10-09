from typing import Any

import httpx


class ContextUnavailable(Exception):
    """The context service could not be reached or failed."""


class ContextRefused(Exception):
    """The context service refused the conversation (403 or 404)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ContextClient:
    """Calls the context service with the JWT of the user and the role of an agent."""

    def __init__(self, http: httpx.AsyncClient, token: str) -> None:
        self._http = http
        self._token = token

    async def _send(self, method: str, path: str, role: str, **kwargs: Any) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "X-Agent-Role": role,
            **kwargs.pop("headers", {}),
        }
        try:
            return await self._http.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as error:
            raise ContextUnavailable(type(error).__name__) from None

    @staticmethod
    def _check(response: httpx.Response, expected: int) -> None:
        if response.status_code in (403, 404):
            error = response.json()["error"]
            raise ContextRefused(response.status_code, error["code"], error["message"])
        if response.status_code != expected:
            raise ContextUnavailable(f"status {response.status_code}")

    async def create_conversation(self) -> str:
        response = await self._send("POST", "/conversations", "orchestrator")
        self._check(response, 201)
        return response.json()["id"]

    async def load(self, conversation_id: str, agent: str) -> dict[str, Any]:
        response = await self._send(
            "GET", f"/conversations/{conversation_id}/context", agent, params={"agent": agent}
        )
        self._check(response, 200)
        return response.json()

    async def add_turn(self, conversation_id: str, role: str, content: str) -> None:
        response = await self._send(
            "POST",
            f"/conversations/{conversation_id}/turns",
            "orchestrator",
            json={"channel": "text", "role": role, "content": content},
        )
        self._check(response, 201)

    async def add_artifact(self, conversation_id: str, type_: str, payload: Any) -> None:
        response = await self._send(
            "POST",
            f"/conversations/{conversation_id}/artifacts",
            "orchestrator",
            json={"type": type_, "payload": payload},
        )
        self._check(response, 201)

    async def put_fact(self, conversation_id: str, key: str, value: Any, version: int) -> None:
        """Write a fact as the orchestrator; `version` is the one the slice showed, or 0."""
        response = await self._send(
            "PUT",
            f"/conversations/{conversation_id}/facts/{key}",
            "orchestrator",
            json={"value": value},
            headers={"If-Match": str(version)},
        )
        self._check(response, 200)
