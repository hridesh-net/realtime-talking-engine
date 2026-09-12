"""Entry point for the interview control-plane FastAPI service."""

from __future__ import annotations

import json
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.utils import is_body_allowed_for_status_code
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from control_plane.api import router as interviews_router
from control_plane.database import init_db


def cors_allowed_origins() -> list[str]:
    """Origins allowed to call this service from a browser, from the environment.

    Comma-separated, whitespace trimmed. Empty or unset means **no CORS
    middleware at all** rather than a permissive default: the browsers that
    matter here carry an organisation cookie, and a wildcard would let any page
    on the internet post a job description and read back a transcript with it.
    """
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _validation_message(errors: list[dict]) -> str:
    """One human-readable line for a body of pydantic validation errors."""
    parts = []
    for error in errors:
        location = ".".join(str(item) for item in error.get("loc", ()))
        message = str(error.get("msg", "invalid"))
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts) or "request validation failed"


def _detail_message(detail: object) -> str:
    """The `message` string for an `HTTPException`'s detail, whatever its shape."""
    if isinstance(detail, str):
        return detail
    return json.dumps(jsonable_encoder(detail))


def install_error_envelope(app: FastAPI) -> None:
    """Add `status` and `message` beside FastAPI's `detail` on every error.

    The existing console reads `detail` and nothing else, so `detail` keeps
    FastAPI's exact value — the string for an `HTTPException`, the list of
    pydantic errors for a validation failure — and the status code is unchanged.
    The two added keys exist for the SkillBrew portal, whose shared axios layer
    toasts `response.data?.message` on 409/422/408 unconditionally and would
    otherwise show an empty toast, and reads a boolean `status` to tell a failure
    from a success body. No success body carries a boolean `status`, so the pair
    is unambiguous.

    Registered on **starlette's** `HTTPException`: `fastapi.HTTPException`
    subclasses it and Starlette resolves a handler by walking the exception's
    MRO, so one registration covers both — including the 404 Starlette itself
    raises for an unmatched route.
    """

    @app.exception_handler(StarletteHTTPException)
    async def http_exception(_request: Request, exc: StarletteHTTPException) -> Response:
        headers = exc.headers
        if not is_body_allowed_for_status_code(exc.status_code):
            # 204 and friends: FastAPI sends no body, and neither may we.
            return Response(status_code=exc.status_code, headers=headers)
        return JSONResponse(
            {
                "detail": exc.detail,
                "status": False,
                "message": _detail_message(exc.detail),
            },
            status_code=exc.status_code,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception(_request: Request, exc: RequestValidationError) -> Response:
        errors = jsonable_encoder(exc.errors())
        return JSONResponse(
            status_code=422,
            content={
                "detail": errors,
                "status": False,
                "message": _validation_message(errors),
            },
        )


def build_app(db_path: str | None = None) -> FastAPI:
    """Construct the control-plane application."""
    logging.basicConfig(level=logging.INFO)
    load_dotenv()  # make GEMINI_API_KEY / OPENAI_API_KEY available
    app = FastAPI(title="Interview Control Plane", version="0.1.0")

    origins = cors_allowed_origins()
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    install_error_envelope(app)

    # Ensure schema exists on startup.
    init_db(db_path).close()

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    app.include_router(interviews_router)
    return app


def main() -> None:
    """Run the service with uvicorn."""
    import uvicorn

    uvicorn.run(
        "control_plane.main:build_app",
        factory=True,
        host="0.0.0.0",
        port=int(os.getenv("CONTROL_PLANE_PORT", "8081")),
        reload=False,
    )


if __name__ == "__main__":
    main()
