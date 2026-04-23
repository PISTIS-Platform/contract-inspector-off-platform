"""Core similarity workflow implementation."""

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from fastapi import HTTPException
from minio.error import S3Error

from ..config import get_settings
from ..schemas import FingerprintSimilarityRequest, FingerprintSimilarityResponse
from .minio_service import get_minio_client, store_object
from .minhash_similarity import FingerprintData, find_similar_fingerprints
from .notifications import notify_similarity_completed

logger = logging.getLogger(__name__)
settings = get_settings()


def _probe_remote_url(url: str, timeout: Optional[int]) -> None:
    """Ensure the remote fingerprint URL is reachable without downloading the payload."""

    request_timeout = timeout or settings.remote_url_timeout_seconds
    response: Optional[requests.Response] = None
    try:
        response = requests.head(url, timeout=request_timeout, allow_redirects=True)
        status_code = response.status_code
    except requests.RequestException as exc:
        logger.error("Failed to reach fingerprint URL %s: %s", url, exc)
        raise HTTPException(status_code=502, detail=f"Failed to reach fingerprint URL: {exc}") from exc
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:  # noqa: BLE001 - best effort cleanup
                pass

    if status_code >= 400:
        try:
            with requests.get(url, stream=True, timeout=request_timeout, allow_redirects=True) as fallback_response:
                status_code = fallback_response.status_code
        except requests.RequestException as exc:
            logger.error("Fallback GET failed for %s: %s", url, exc)
            raise HTTPException(status_code=502, detail=f"Failed to reach fingerprint URL: {exc}") from exc

    if status_code >= 400:
        logger.error("Fingerprint URL returned HTTP %s for %s", status_code, url)
        raise HTTPException(
            status_code=404,
            detail=f"Fingerprint URL returned HTTP {status_code}",
        )
def _safe_dataset_segment(dataset_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", dataset_id.strip())
    return safe or "dataset"


def _fingerprint_filename(remote_url: str) -> str:
    return Path(urlparse(remote_url).path).name or "fingerprint.bin"


def _fingerprint_object_name(dataset_id: str, fingerprint_filename: str) -> str:
    prefix = settings.fingerprint_prefix.strip("/")
    parts = []
    if prefix:
        parts.append(prefix)
    if dataset_id:
        parts.append(dataset_id)
    parts.append(fingerprint_filename)
    return "/".join(parts)


def _similarity_object_name(dataset_id: str, fingerprint_filename: str) -> str:
    prefix = settings.similarity_result_prefix.strip("/")
    json_name = f"{Path(fingerprint_filename).stem}.json"
    parts = []
    if prefix:
        parts.append(prefix)
    if dataset_id:
        parts.append(dataset_id)
    parts.append(json_name)
    return "/".join(parts)


def _fetch_remote_payload(url: str) -> tuple[bytes, str]:
    try:
        with requests.get(url, stream=True, timeout=settings.remote_url_timeout_seconds, allow_redirects=True) as response:
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=f"Download failed with status {response.status_code}",
                )
            data = response.content
            content_type = response.headers.get("Content-Type", "application/octet-stream")
    except requests.RequestException as exc:
        logger.error("Failed to download fingerprint from %s: %s", url, exc)
        raise HTTPException(status_code=502, detail=f"Failed to download fingerprint: {exc}") from exc

    return data, content_type


def _fetch_existing_fingerprints(client, bucket: str) -> list[FingerprintData]:
    """Fetch all existing fingerprints from MinIO.

    Args:
        client: MinIO client instance
        bucket: Bucket name

    Returns:
        List of FingerprintData objects for all fingerprints in storage
    """
    fingerprints = []
    prefix = settings.fingerprint_prefix.strip("/")

    try:
        objects = client.list_objects(bucket, prefix=prefix, recursive=True)

        for obj in objects:
            # Skip directories and non-JSON files
            if obj.object_name.endswith("/"):
                continue

            # Only process JSON fingerprint files (from Airflow DAG)
            if not obj.object_name.endswith(".json"):
                continue

            try:
                # Read the fingerprint file
                response = client.get_object(bucket, obj.object_name)
                data = response.read()
                response.close()
                response.release_conn()

                # Parse JSON to extract dataset_id
                parsed = json.loads(data)
                extracted_dataset_id = parsed.get("dataset_id", "unknown")
                source_url = parsed.get("source_url", obj.object_name)

                # Parse fingerprint data
                fingerprint_data = FingerprintData.from_json(
                    data,
                    dataset_id=extracted_dataset_id,
                    source_url=source_url,
                )
                fingerprints.append(fingerprint_data)

                logger.debug("Loaded fingerprint for dataset %s from %s", extracted_dataset_id, obj.object_name)

            except (ValueError, json.JSONDecodeError) as exc:
                logger.warning("Failed to parse fingerprint %s: %s", obj.object_name, exc)
                continue
            except S3Error as exc:
                logger.warning("Failed to read fingerprint %s: %s", obj.object_name, exc)
                continue

    except S3Error as exc:
        logger.error("Failed to list fingerprints from %s/%s: %s", bucket, prefix, exc)

    logger.info("Loaded %d existing fingerprints for comparison", len(fingerprints))
    return fingerprints


def _store_and_compute_similarity(
    dataset_id: str,
    fingerprint_payload: bytes,
    fingerprint_filename: str,
    content_type: str,
    source_url: Optional[str],
    seller_id: Optional[str] = None,
    buyer_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> None:
    client = get_minio_client(settings)
    bucket = settings.local_minio_bucket

    fingerprint_object = _fingerprint_object_name(dataset_id, fingerprint_filename)
    logger.info("Storing fingerprint for dataset %s as %s/%s", dataset_id, bucket, fingerprint_object)

    try:
        store_object(
            client,
            bucket,
            fingerprint_object,
            fingerprint_payload,
            content_type=content_type,
        )
    except Exception as exc:  # pragma: no cover - logged and abort
        logger.error("Failed to store fingerprint for dataset %s: %s", dataset_id, exc)
        return

    # Compute similarities with existing fingerprints
    matches = []
    try:
        # Parse the current fingerprint
        current_fingerprint = FingerprintData.from_json(
            fingerprint_payload,
            dataset_id=dataset_id,
            source_url=source_url or "",
        )

        # Fetch all existing fingerprints
        existing_fingerprints = _fetch_existing_fingerprints(client, bucket)

        # Find similar fingerprints
        matches = find_similar_fingerprints(
            current_fingerprint,
            existing_fingerprints,
            threshold=settings.similarity_threshold,
        )

        logger.info("Found %d similar fingerprints for dataset %s", len(matches), dataset_id)
        for match in matches:
            logger.info(
                "  - Dataset %s: similarity=%.4f",
                match["dataset_id"],
                match["similarity_score"],
            )

    except ValueError as exc:
        logger.error("Failed to compute similarities for dataset %s: %s", dataset_id, exc)
    except Exception as exc:  # pragma: no cover
        logger.error("Unexpected error during similarity computation for dataset %s: %s", dataset_id, exc)

    similarity_payload = {
        "dataset_id": dataset_id,
        "fingerprint_object": fingerprint_object,
        "source_url": source_url,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "completed",
        "matches": matches,
    }
    similarity_bytes = json.dumps(similarity_payload, indent=2).encode("utf-8")
    similarity_object = _similarity_object_name(dataset_id, fingerprint_filename)
    logger.info("Writing similarity result for dataset %s to %s/%s", dataset_id, bucket, similarity_object)

    try:
        store_object(
            client,
            bucket,
            similarity_object,
            similarity_bytes,
            content_type="application/json",
        )
    except Exception as exc:  # pragma: no cover - logged and abort
        logger.error("Failed to store similarity result for dataset %s: %s", dataset_id, exc)
        return

    notify_similarity_completed(
        user_ids=(seller_id, buyer_id),
        access_token=access_token,
        dataset_id=dataset_id,
        match_count=len(matches),
    )


def _download_to_disk(
    url: str,
    dataset_id: str,
    seller_id: Optional[str] = None,
    buyer_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> None:
    try:
        fingerprint_payload, content_type = _fetch_remote_payload(url)
    except HTTPException as exc:  # pragma: no cover - logged and ignored
        logger.error("Dataset %s download aborted: %s", dataset_id, exc.detail)
        return

    fingerprint_filename = _fingerprint_filename(url)
    _store_and_compute_similarity(
        dataset_id=dataset_id,
        fingerprint_payload=fingerprint_payload,
        fingerprint_filename=fingerprint_filename,
        content_type=content_type,
        source_url=url,
        seller_id=seller_id,
        buyer_id=buyer_id,
        access_token=access_token,
    )


def _process_inline_fingerprint(
    dataset_id: str,
    fingerprint_dict: dict[str, Any],
    source_url: Optional[str],
    seller_id: Optional[str] = None,
    buyer_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> None:
    fingerprint_payload = json.dumps(fingerprint_dict).encode("utf-8")
    fingerprint_filename = f"{_safe_dataset_segment(dataset_id)}.json"
    _store_and_compute_similarity(
        dataset_id=dataset_id,
        fingerprint_payload=fingerprint_payload,
        fingerprint_filename=fingerprint_filename,
        content_type="application/json",
        source_url=source_url,
        seller_id=seller_id,
        buyer_id=buyer_id,
        access_token=access_token,
    )


def _start_download_thread(
    url: str,
    dataset_id: str,
    seller_id: Optional[str] = None,
    buyer_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> None:
    logger.info("Starting download worker for dataset %s", dataset_id)
    thread = threading.Thread(
        target=_download_to_disk,
        args=(url, dataset_id, seller_id, buyer_id, access_token),
        name=f"download-{_safe_dataset_segment(dataset_id)}",
        daemon=True,
    )
    thread.start()


def _start_inline_thread(
    dataset_id: str,
    fingerprint_dict: dict[str, Any],
    source_url: Optional[str],
    seller_id: Optional[str] = None,
    buyer_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> None:
    logger.info("Starting inline fingerprint worker for dataset %s", dataset_id)
    thread = threading.Thread(
        target=_process_inline_fingerprint,
        args=(dataset_id, fingerprint_dict, source_url, seller_id, buyer_id, access_token),
        name=f"inline-{_safe_dataset_segment(dataset_id)}",
        daemon=True,
    )
    thread.start()


def acknowledge_similarity_request(
    request: FingerprintSimilarityRequest,
) -> FingerprintSimilarityResponse:
    """Validate the incoming request, trigger download, and return an acknowledgement."""

    dataset_id = request.dataset_id.strip()
    if not dataset_id:
        raise HTTPException(status_code=400, detail="dataset_id must not be blank")

    logger.info("Received similarity request for dataset %s", dataset_id)

    if request.fingerprint is not None:
        _start_inline_thread(
            dataset_id,
            request.fingerprint,
            request.source_url,
            seller_id=request.seller_id,
            buyer_id=request.buyer_id,
            access_token=request.access_token,
        )
        logger.info("Inline similarity request for dataset %s acknowledged", dataset_id)
        return FingerprintSimilarityResponse(
            dataset_id=dataset_id,
            fingerprint_url=None,
            status="accepted",
            remote_object_available=True,
        )

    _probe_remote_url(str(request.fingerprint_url), timeout=settings.remote_url_timeout_seconds)
    logger.info("Fingerprint URL validated for dataset %s", dataset_id)
    _start_download_thread(
        str(request.fingerprint_url),
        dataset_id,
        seller_id=request.seller_id,
        buyer_id=request.buyer_id,
        access_token=request.access_token,
    )
    logger.info("Similarity request for dataset %s acknowledged", dataset_id)

    return FingerprintSimilarityResponse(
        dataset_id=dataset_id,
        fingerprint_url=request.fingerprint_url,
        status="accepted",
        remote_object_available=True,
    )
