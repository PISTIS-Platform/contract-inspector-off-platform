"""Tests for the similarity API acknowledgement workflow."""

from __future__ import annotations

import io
import json
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from minio import Minio
from minio.error import S3Error

from app.config import get_settings
from app.services.similarity import (
    _fingerprint_filename,
    _fingerprint_object_name,
    _similarity_object_name,
)

DATASET_PATH = Path(__file__).resolve().parents[1] / "tests" / "data" / "dataset.json"
SETTINGS = get_settings()


@pytest.fixture(scope="session")
def dataset_payload() -> bytes:
    return DATASET_PATH.read_bytes()


@pytest.fixture()
def dataset_object(minio_remote_client: Minio, dataset_payload: bytes):
    bucket = SETTINGS.remote_minio_bucket
    object_name = f"datasets/{uuid.uuid4().hex}.json"

    minio_remote_client.put_object(
        bucket,
        object_name,
        io.BytesIO(dataset_payload),
        length=len(dataset_payload),
        content_type="application/json",
    )

    presigned_url = minio_remote_client.presigned_get_object(
        bucket,
        object_name,
        expires=timedelta(minutes=5),
    )

    yield {
        "bucket": bucket,
        "object_name": object_name,
        "url": presigned_url,
    }

    try:
        minio_remote_client.remove_object(bucket, object_name)
    except S3Error as exc:
        if exc.code != "NoSuchKey":
            raise
    # Keep shared bucket for subsequent tests


def _wait_for_minio_object(client: Minio, bucket: str, object_name: str, timeout: float = 5.0) -> Minio:
    deadline = time.time() + timeout
    last_exc: S3Error | None = None
    while time.time() < deadline:
        try:
            client.stat_object(bucket, object_name)
            return client
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchBucket"}:
                last_exc = exc
                time.sleep(0.1)
                continue
            raise
    if last_exc:
        raise AssertionError(f"Object {bucket}/{object_name} not found: {last_exc}")
    raise AssertionError(f"Object {bucket}/{object_name} not found within timeout")


def _read_object(client: Minio, bucket: str, object_name: str) -> bytes:
    response = client.get_object(bucket, object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _remove_object(client: Minio, bucket: str, object_name: str) -> None:
    try:
        client.remove_object(bucket, object_name)
    except S3Error as exc:
        if exc.code not in {"NoSuchKey", "NoSuchBucket"}:
            raise


def test_similarity_request_acknowledged(api_client, dataset_object, dataset_payload, minio_local_client):
    dataset_id = f"1_jcmanual__2025-08-04T10_28_15.596898+00_00_jc"

    response = api_client.post(
        "/similarity",
        json={
            "fingerprint_url": dataset_object["url"],
            "dataset_id": dataset_id,
        },
    )

    assert response.status_code == 202
    body = response.json()

    assert body == {
        "dataset_id": dataset_id,
        "fingerprint_url": dataset_object["url"],
        "status": "accepted",
        "remote_object_available": True,
    }

    fingerprint_filename = _fingerprint_filename(dataset_object["url"])
    fingerprint_object = _fingerprint_object_name(dataset_id, fingerprint_filename)
    _wait_for_minio_object(
        minio_local_client,
        SETTINGS.local_minio_bucket,
        fingerprint_object,
    )
    stored_bytes = _read_object(
        minio_local_client,
        SETTINGS.local_minio_bucket,
        fingerprint_object,
    )
    assert stored_bytes == dataset_payload

    similarity_object = _similarity_object_name(dataset_id, fingerprint_filename)
    _wait_for_minio_object(
        minio_local_client,
        SETTINGS.local_minio_bucket,
        similarity_object,
    )
    similarity_bytes = _read_object(
        minio_local_client,
        SETTINGS.local_minio_bucket,
        similarity_object,
    )
    similarity_data = json.loads(similarity_bytes)
    assert similarity_data["dataset_id"] == dataset_id
    assert similarity_data["fingerprint_object"] == fingerprint_object

    # _remove_object(minio_local_client, SETTINGS.local_minio_bucket, fingerprint_object)
    # _remove_object(minio_local_client, SETTINGS.similarity_result_bucket, similarity_object)


def test_similarity_request_missing_remote_object(api_client, dataset_object, minio_local_client):
    dataset_id = f"dataset_{uuid.uuid4().hex[:8]}"
    missing_url = dataset_object["url"].replace(dataset_object["object_name"], "does-not-exist.json")

    response = api_client.post(
        "/similarity",
        json={
            "fingerprint_url": missing_url,
            "dataset_id": dataset_id,
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"].startswith("Fingerprint URL returned HTTP")

    fingerprint_filename = _fingerprint_filename(missing_url)
    fingerprint_object = _fingerprint_object_name(dataset_id, fingerprint_filename)
    similarity_object = _similarity_object_name(dataset_id, fingerprint_filename)

    for bucket, obj in (
        (SETTINGS.local_minio_bucket, fingerprint_object),
        (SETTINGS.local_minio_bucket, similarity_object),
    ):
        try:
            minio_local_client.stat_object(bucket, obj)
        except S3Error as exc:
            assert exc.code in {"NoSuchKey", "NoSuchBucket"}
        else:
            raise AssertionError(f"Unexpected object present: {bucket}/{obj}")
