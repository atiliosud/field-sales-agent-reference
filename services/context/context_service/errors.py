from typing import Any


class ApiError(Exception):
    """A failure reported to the caller using the error format of the contract."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_body(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def unauthenticated(message: str) -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", message)


def forbidden(message: str) -> ApiError:
    return ApiError(403, "FORBIDDEN", message)


def not_found(message: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", message)


def invalid_input(message: str) -> ApiError:
    return ApiError(400, "INVALID_INPUT", message)


def conflict(message: str) -> ApiError:
    return ApiError(409, "CONFLICT", message)
