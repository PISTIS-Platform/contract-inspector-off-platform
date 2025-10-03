"""API routers for the similarity service."""

from .health import router as health_router
from .similarity import router as similarity_router

__all__ = ["health_router", "similarity_router"]
