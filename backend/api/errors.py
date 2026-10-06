"""The one REST error shape and the handlers that produce it (API and Contracts sections 23 to 25).

Every error the API returns is `{"error": {code, message, details, retryable, diagnostic_id}}`:

* an `ApiError` a route raises on purpose is mapped to its status and code;
* a request that fails validation is normalized to `422 VALIDATION_ERROR`, naming the field and the
  rule but never echoing what the client sent (it may be a path or personal data);
* an unknown route or method is `NOT_FOUND` / `METHOD_NOT_ALLOWED`;
* anything unexpected is `500 INTERNAL_ERROR` with a diagnostic id and nothing else: no message, no
  traceback. The diagnostic id is logged with the exception, so a report can be matched to the log
  (which stays on the machine).
"""

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

LOG = logging.getLogger("faceidentify.api")

_HTTP_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


class ApiError(Exception):
    """An expected application error with a stable machine code (section 24)."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.retryable = retryable


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
    diagnostic_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "retryable": retryable,
                "diagnostic_id": diagnostic_id,
            }
        },
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_request: Request, error: ApiError) -> JSONResponse:
        return error_response(
            error.status_code,
            error.code,
            error.message,
            details=error.details,
            retryable=error.retryable,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
        fields = [
            {"location": list(item["loc"]), "type": item["type"], "message": item["msg"]}
            for item in error.errors()  # (never `input`: it is what the client sent)
        ]
        return error_response(
            422, "VALIDATION_ERROR", "The request is not valid.", details={"fields": fields}
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(error.status_code, "HTTP_ERROR")
        return error_response(error.status_code, code, "The request could not be served.")

    @app.exception_handler(Exception)
    async def unexpected(_request: Request, error: Exception) -> JSONResponse:
        diagnostic_id = uuid.uuid4().hex
        LOG.error(
            "unhandled %s [diagnostic %s]", type(error).__name__, diagnostic_id, exc_info=error
        )
        return error_response(
            500,
            "INTERNAL_ERROR",
            "An unexpected error occurred.",
            diagnostic_id=diagnostic_id,
        )
