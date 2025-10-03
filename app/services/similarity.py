"""Core similarity workflow implementation."""

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from fastapi import HTTPException

from ..config import get_settings
from ..schemas import FingerprintSimilarityRequest, FingerprintSimilarityResponse
from .minio_service import get_minio_client, store_object

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


def _download_to_disk(url: str, dataset_id: str) -> None:
    try:
        fingerprint_payload, content_type = _fetch_remote_payload(url)
    except HTTPException as exc:  # pragma: no cover - logged and ignored
        logger.error("Dataset %s download aborted: %s", dataset_id, exc.detail)
        return

    client = get_minio_client(settings)
    bucket = settings.local_minio_bucket

    fingerprint_filename = _fingerprint_filename(url)
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

    similarity_payload = {
        "dataset_id": dataset_id,
        "fingerprint_object": fingerprint_object,
        "source_url": url,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "completed",
        "matches": [],
    }
    similarity_bytes = json.dumps(similarity_payload, indent=2).encode("utf-8")
    similarity_object = _similarity_object_name(dataset_id, fingerprint_filename)
    logger.info("Writing similarity stub for dataset %s to %s/%s", dataset_id, bucket, similarity_object)

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


def _start_download_thread(url: str, dataset_id: str) -> None:
    thread = threading.Thread(
        target=_download_to_disk,
        args=(url, dataset_id),
        name=f"download-{_safe_dataset_segment(dataset_id)}",
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
    _probe_remote_url(str(request.fingerprint_url), timeout=settings.remote_url_timeout_seconds)
    _start_download_thread(str(request.fingerprint_url), dataset_id)

    return FingerprintSimilarityResponse(
        dataset_id=dataset_id,
        fingerprint_url=request.fingerprint_url,
        status="accepted",
        remote_object_available=True,
    )
