"""Helpers for interacting with MinIO."""

from __future__ import annotations

import io
import logging
from minio import Minio

from ..config import Settings

logger = logging.getLogger(__name__)


def get_minio_client(settings: Settings) -> Minio:
    """Create a MinIO client using the provided settings."""

    logger.debug(
        "Creating MinIO client for %s (secure=%s)",
        settings.local_minio_endpoint,
        settings.local_minio_secure,
    )
    return Minio(
        settings.local_minio_endpoint,
        access_key=settings.local_minio_access_key,
        secret_key=settings.local_minio_secret_key,
        secure=settings.local_minio_secure,
    )
def store_object(
    client: Minio,
    bucket: str,
    object_name: str,
    payload: bytes,
    *,
    content_type: str,
) -> None:
    """Store a payload in MinIO."""

    try:
        client.put_object(
            bucket,
            object_name,
            io.BytesIO(payload),
            length=len(payload),
            content_type=content_type,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to store %s/%s: %s", bucket, object_name, exc)
        raise
