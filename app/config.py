"""Configuration helpers for the similarity service."""

from __future__ import annotations

import os
from functools import lru_cache


class Settings:
    """Service configuration sourced from environment variables."""

    def __init__(self) -> None:
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.remote_url_timeout_seconds = _int_env("REMOTE_URL_TIMEOUT_SECONDS", default=10)

        self.api_title = os.getenv("SIMILARITY_API_TITLE", "Fingerprint Similarity Service")
        self.api_description = os.getenv(
            "SIMILARITY_API_DESCRIPTION",
            "Accepts fingerprint payloads, stores them in MinIO, and produces similarity results.",
        )
        self.api_version = os.getenv("SIMILARITY_API_VERSION", "0.1.0")
        self.api_host = os.getenv("SIMILARITY_API_HOST", "0.0.0.0")
        self.api_port = _int_env("SIMILARITY_API_PORT", default=8000)
        self.api_reload = _bool_env("SIMILARITY_API_RELOAD", default=False)

        self.fingerprint_prefix = os.getenv("FINGERPRINT_PREFIX", "fingerprints/")
        self.similarity_result_prefix = os.getenv("SIMILARITY_RESULT_PREFIX", "similarity/")
        self.similarity_threshold = _float_env("SIMILARITY_THRESHOLD", default=0.7)

        # Used only for tests
        self.remote_minio_bucket = os.getenv("REMOTE_MINIO_BUCKET", "pistis")
        self.remote_minio_endpoint = os.getenv("REMOTE_MINIO_ENDPOINT", "localhost:9002")
        self.remote_minio_secure = _bool_env("REMOTE_MINIO_SECURE", default=False)

        # Required to be set by env
        self.local_minio_endpoint = os.getenv("LOCAL_MINIO_ENDPOINT", "localhost:9000")
        self.local_minio_access_key = os.getenv("LOCAL_MINIO_ACCESS_KEY", "localadmin")
        self.local_minio_secret_key = os.getenv("LOCAL_MINIO_SECRET_KEY", "localsecret123")
        self.local_minio_secure = _bool_env("LOCAL_MINIO_SECURE", default=False)
        self.local_minio_bucket = os.getenv("LOCAL_MINIO_BUCKET", "pistis")

        self.notifications_url = os.getenv(
            "NOTIFICATIONS_URL",
            "http://notifications.default.svc.cluster.local:3000/api/notifications",
        )
        self.notifications_timeout_seconds = _int_env("NOTIFICATIONS_TIMEOUT_SECONDS", default=10)




def _int_env(name: str, *, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool_env(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, *, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()
