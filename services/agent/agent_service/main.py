import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from agent_service.auth import Caller, authenticated
from agent_service.config import Settings
from agent_service.errors import ApiError, error_body
from agent_service.prompts import load_prompt
from agent_service.turn import ChatService

logger = logging.getLogger(__name__)


class ChatIn(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1)
    confirm: bool = False


def create_app(settings: Settings | None = None, model: BaseChatModel | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config = settings or Settings.from_env()
        app.state.chat = ChatService(
            config,
            model,
            load_prompt(config.prompt_orchestrator),
            load_prompt(config.prompt_specialist),
        )
        yield

    app = FastAPI(title="agent-service", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/chat")
    async def chat(
        body: ChatIn, caller: Annotated[Caller, Depends(authenticated)], request: Request
    ) -> dict[str, object]:
        service: ChatService = request.app.state.chat
        result = await service.chat(caller.token, body.conversation_id, body.message, body.confirm)
        response: dict[str, object] = {
            "conversation_id": result.conversation_id,
            "answer": result.answer,
        }
        if result.pending_action:
            response["pending_action"] = result.pending_action
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(error_body(error.code, error.message), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        fields = sorted({".".join(str(part) for part in e["loc"]) for e in error.errors()})
        message = f"Invalid request: {', '.join(fields)}."
        return JSONResponse(error_body("INVALID_INPUT", message), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = "NOT_FOUND" if error.status_code == 404 else "INVALID_INPUT"
        message = (
            "The resource was not found." if code == "NOT_FOUND" else "The request is not valid."
        )
        return JSONResponse(error_body(code, message), status_code=error.status_code)

    @app.middleware("http")
    async def internal_errors(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except Exception as error:
            logger.error("Unexpected failure: %s", type(error).__name__)
            body = error_body("INTERNAL", "The request could not be completed.")
            return JSONResponse(body, status_code=500)

    return app


app = create_app()
