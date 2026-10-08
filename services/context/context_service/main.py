import asyncio
import logging
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.exceptions import HTTPException as StarletteHTTPException

from context_service import telemetry
from context_service.api import router
from context_service.db import migrate
from context_service.errors import ApiError, error_body

telemetry.setup()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database_url = os.environ["DATABASE_URL"]
    await asyncio.to_thread(migrate, database_url)
    engine = create_async_engine(database_url)
    app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
    yield
    await engine.dispose()


def error_response(status: int, code: str, message: str) -> JSONResponse:
    telemetry.mark_failed(code)
    return JSONResponse(error_body(code, message), status_code=status)


async def api_error_handler(request: Request, error: ApiError) -> JSONResponse:
    return error_response(error.status, error.code, error.message)


async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    fields = sorted({".".join(str(part) for part in e["loc"]) for e in error.errors()})
    return error_response(400, "INVALID_INPUT", f"Invalid request: {', '.join(fields)}.")


async def http_error_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
    if error.status_code == 404:
        return error_response(404, "NOT_FOUND", "The resource was not found.")
    return error_response(error.status_code, "INVALID_INPUT", "The request is not valid.")


def note_session(request: Request) -> None:
    try:
        conversation_id = uuid.UUID(request.path_params.get("conversation_id", ""))
    except ValueError:
        return
    telemetry.set_attribute("session.id", str(conversation_id))


async def internal_error_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    try:
        response = await call_next(request)
    except Exception as error:
        logger.error("Unexpected failure: %s", type(error).__name__)
        response = error_response(500, "INTERNAL", "The request could not be completed.")
    note_session(request)
    return response


def create_app() -> FastAPI:
    app = FastAPI(
        title="context-service",
        lifespan=lifespan,
        telemetry={
            "operation_spans": False,
            "metrics": False,
            "logs": False,
            "auto_configure": False,
            "exclude": lambda scope: scope.get("path") == "/health",
        },
    )
    app.include_router(router)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.middleware("http")(internal_error_middleware)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
