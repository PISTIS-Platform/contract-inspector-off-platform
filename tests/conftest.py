"""Shared pytest fixtures for the similarity API tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from minio import Minio
from minio.error import S3Error

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:  # Ensure the app package is discoverable
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("LOCAL_MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("LOCAL_MINIO_ACCESS_KEY", "localadmin")
os.environ.setdefault("LOCAL_MINIO_SECRET_KEY", "localsecret123")
os.environ.setdefault("LOCAL_MINIO_SECURE", "false")
os.environ.setdefault("LOCAL_MINIO_BUCKET", "pistis")
os.environ.setdefault("FINGERPRINT_PREFIX", "fingerprints")
os.environ.setdefault("SIMILARITY_RESULT_PREFIX", "similarity")
os.environ.setdefault("REMOTE_MINIO_BUCKET", "pistis")

from app.config import get_settings
from app.main import create_app

SETTINGS = get_settings()


def _env_flag(value: str | None) -> bool:
    return (value or "false").lower() in {"1", "true", "yes", "on"}


def _build_minio_client(*, endpoint: str, access_key: str, secret_key: str, secure: bool) -> Minio:
    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
    try:
        client.list_buckets()
    except Exception as exc:  # noqa: BLE001 - best effort connectivity probe
        pytest.skip(f"Unable to reach MinIO at {endpoint}: {exc}")
    return client


@pytest.fixture(scope="session")
def minio_remote_client() -> Minio:
    endpoint = os.getenv("REMOTE_MINIO_ENDPOINT", "localhost:9002")
    access_key = os.getenv("REMOTE_MINIO_ACCESS_KEY", "remoteadmin")
    secret_key = os.getenv("REMOTE_MINIO_SECRET_KEY", "remotesecret123")
    secure = _env_flag(os.getenv("REMOTE_MINIO_SECURE"))
    client = _build_minio_client(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
    )
    try:
        client.make_bucket(SETTINGS.remote_minio_bucket)
    except S3Error as exc:
        if exc.code not in {"BucketAlreadyExists", "BucketAlreadyOwnedByYou"}:
            raise
    return client


@pytest.fixture(scope="session")
def minio_local_client() -> Minio:
    endpoint = os.environ["LOCAL_MINIO_ENDPOINT"]
    access_key = os.environ["LOCAL_MINIO_ACCESS_KEY"]
    secret_key = os.environ["LOCAL_MINIO_SECRET_KEY"]
    secure = _env_flag(os.environ.get("LOCAL_MINIO_SECURE"))
    client = _build_minio_client(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
    )
    try:
        client.make_bucket(SETTINGS.local_minio_bucket)
    except S3Error as exc:
        if exc.code not in {"BucketAlreadyExists", "BucketAlreadyOwnedByYou"}:
            raise
    return client


@pytest.fixture(scope="session")
def app_instance():  # type: ignore[override]
    return create_app()


@pytest.fixture()
def api_client(app_instance) -> Iterator[TestClient]:
    with TestClient(app_instance) as client:
        yield client
