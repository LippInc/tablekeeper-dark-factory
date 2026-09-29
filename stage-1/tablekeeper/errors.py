"""The error model (§5): every 4xx and 5xx carries `{"error": {"code", "message"}}`."""
from __future__ import annotations


class ApiError(Exception):
    """A request the service refuses, with its HTTP status and error code."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


def malformed(message: str) -> ApiError:
    return ApiError(400, "malformed_request", message)


def unauthenticated(message: str) -> ApiError:
    return ApiError(401, "unauthenticated", message)


def not_found(message: str) -> ApiError:
    return ApiError(404, "not_found", message)


def invalid(message: str) -> ApiError:
    return ApiError(422, "validation_failed", message)
