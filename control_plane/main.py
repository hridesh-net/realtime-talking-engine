"""Entry point for the interview control-plane FastAPI service."""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI

from control_plane.api import router as interviews_router
from control_plane.database import init_db


def build_app(db_path: str | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    load_dotenv()  # make GEMINI_API_KEY / OPENAI_API_KEY available
    app = FastAPI(title="Interview Control Plane", version="0.1.0")

    # Ensure schema exists on startup.
    init_db(db_path).close()

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    app.include_router(interviews_router)
    return app


def main() -> None:
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
