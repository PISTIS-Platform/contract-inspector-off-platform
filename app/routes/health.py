"""Health check endpoint."""

from typing import Dict

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}
