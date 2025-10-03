"""FastAPI application setup."""

import logging

from fastapi import FastAPI

from .config import get_settings
from .routes import health_router, similarity_router


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""

    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    app = FastAPI(
        title=settings.api_title,
        description=settings.api_description,
        version=settings.api_version,
    )
    app.include_router(similarity_router)
    app.include_router(health_router)
    return app


app = create_app()


def run() -> None:
    """Run the API using uvicorn."""

    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
    )
