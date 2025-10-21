"""Tests for the similarity search API endpoint."""

import io
import json

import pytest
from minio import Minio

from app.config import get_settings

SETTINGS = get_settings()


@pytest.fixture()
def sample_similarity_result():
    """Sample similarity result JSON for testing."""
    return {
        "dataset_id": "test-dataset-123",
        "fingerprint_object": "fingerprints/test-dataset-123/data.csv",
        "source_url": "http://example.com/data.csv",
        "generated_at": "2025-10-21T14:30:45Z",
        "status": "completed",
        "matches": [
            {
                "dataset_id": "similar-dataset-1",
                "similarity_score": 0.9234,
                "algorithm": "adhoc_minhash",
                "source_url": "http://example.com/similar1.csv"
            },
            {
                "dataset_id": "similar-dataset-2",
                "similarity_score": 0.7891,
                "algorithm": "adhoc_minhash",
                "source_url": "http://example.com/similar2.csv"
            }
        ]
    }


@pytest.fixture()
def stored_similarity_result(minio_local_client: Minio, sample_similarity_result):
    """Store a similarity result in MinIO for testing."""
    bucket = SETTINGS.local_minio_bucket
    dataset_id = sample_similarity_result["dataset_id"]
    object_name = f"{SETTINGS.similarity_result_prefix.strip('/')}/{dataset_id}/result.json"

    # Convert to bytes
    json_data = json.dumps(sample_similarity_result, indent=2).encode('utf-8')

    # Store in MinIO
    minio_local_client.put_object(
        bucket,
        object_name,
        data=io.BytesIO(json_data),
        length=len(json_data),
        content_type='application/json'
    )

    yield {
        "bucket": bucket,
        "object_name": object_name,
        "dataset_id": dataset_id,
        "data": sample_similarity_result
    }

    # Cleanup
    try:
        minio_local_client.remove_object(bucket, object_name)
    except Exception:
        pass


def test_search_existing_dataset(api_client, stored_similarity_result):
    """Test searching for a dataset that exists."""
    dataset_id = stored_similarity_result["dataset_id"]

    response = api_client.get(f"/search?dataset_id={dataset_id}")

    assert response.status_code == 200
    body = response.json()

    assert body["dataset_id"] == dataset_id
    assert body["status"] == "completed"
    assert body["fingerprint_object"] == "fingerprints/test-dataset-123/data.csv"
    assert body["source_url"] == "http://example.com/data.csv"
    assert body["generated_at"] == "2025-10-21T14:30:45Z"
    assert body["match_count"] == 2

    # Check matches
    assert len(body["matches"]) == 2
    assert body["matches"][0]["dataset_id"] == "similar-dataset-1"
    assert body["matches"][0]["similarity_score"] == 0.9234
    assert body["matches"][0]["algorithm"] == "adhoc_minhash"
    assert body["matches"][1]["dataset_id"] == "similar-dataset-2"
    assert body["matches"][1]["similarity_score"] == 0.7891


def test_search_nonexistent_dataset(api_client):
    """Test searching for a dataset that doesn't exist."""
    response = api_client.get("/search?dataset_id=nonexistent-dataset-999")

    assert response.status_code == 404
    body = response.json()
    assert "not found" in body["detail"].lower()


def test_search_empty_dataset_id(api_client):
    """Test searching with empty dataset_id."""
    response = api_client.get("/search?dataset_id=")

    assert response.status_code == 422  # Pydantic validation error


def test_search_blank_dataset_id(api_client):
    """Test searching with blank dataset_id."""
    response = api_client.get("/search?dataset_id=%20%20%20")  # URL-encoded spaces

    assert response.status_code == 400
    body = response.json()
    assert "blank" in body["detail"].lower()


def test_search_missing_dataset_id(api_client):
    """Test searching without dataset_id parameter."""
    response = api_client.get("/search")

    assert response.status_code == 422  # Pydantic validation error


def test_search_dataset_with_no_matches(minio_local_client: Minio, api_client):
    """Test searching for a dataset with no similarity matches."""
    dataset_id = "dataset-no-matches"
    similarity_result = {
        "dataset_id": dataset_id,
        "fingerprint_object": f"fingerprints/{dataset_id}/data.csv",
        "source_url": "http://example.com/data.csv",
        "generated_at": "2025-10-21T15:00:00Z",
        "status": "completed",
        "matches": []
    }

    bucket = SETTINGS.local_minio_bucket
    object_name = f"{SETTINGS.similarity_result_prefix.strip('/')}/{dataset_id}/result.json"

    # Store in MinIO
    json_data = json.dumps(similarity_result, indent=2).encode('utf-8')
    minio_local_client.put_object(
        bucket,
        object_name,
        data=io.BytesIO(json_data),
        length=len(json_data),
        content_type='application/json'
    )

    try:
        response = api_client.get(f"/search?dataset_id={dataset_id}")

        assert response.status_code == 200
        body = response.json()

        assert body["dataset_id"] == dataset_id
        assert body["status"] == "completed"
        assert body["match_count"] == 0
        assert body["matches"] == []

    finally:
        # Cleanup
        try:
            minio_local_client.remove_object(bucket, object_name)
        except Exception:
            pass


def test_search_dataset_special_characters(minio_local_client: Minio, api_client):
    """Test searching for a dataset with special characters in ID."""
    dataset_id = "test_dataset-2025.01.01"
    similarity_result = {
        "dataset_id": dataset_id,
        "fingerprint_object": f"fingerprints/{dataset_id}/data.csv",
        "source_url": "http://example.com/data.csv",
        "generated_at": "2025-10-21T15:00:00Z",
        "status": "completed",
        "matches": []
    }

    bucket = SETTINGS.local_minio_bucket
    object_name = f"{SETTINGS.similarity_result_prefix.strip('/')}/{dataset_id}/result.json"

    # Store in MinIO
    json_data = json.dumps(similarity_result, indent=2).encode('utf-8')
    minio_local_client.put_object(
        bucket,
        object_name,
        data=io.BytesIO(json_data),
        length=len(json_data),
        content_type='application/json'
    )

    try:
        # URL encode the dataset_id
        import urllib.parse
        encoded_id = urllib.parse.quote(dataset_id)
        response = api_client.get(f"/search?dataset_id={encoded_id}")

        assert response.status_code == 200
        body = response.json()

        assert body["dataset_id"] == dataset_id
        assert body["status"] == "completed"

    finally:
        # Cleanup
        try:
            minio_local_client.remove_object(bucket, object_name)
        except Exception:
            pass