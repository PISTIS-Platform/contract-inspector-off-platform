"""Service for searching and retrieving similarity results."""

import json
import logging
from typing import Optional

from minio import Minio
from minio.error import S3Error

from ..config import get_settings
from ..schemas import SimilarityMatch, SimilaritySearchResponse

logger = logging.getLogger(__name__)
settings = get_settings()


def _find_similarity_result_for_dataset(client: Minio, bucket: str, dataset_id: str) -> Optional[tuple[str, dict]]:
    """Find the similarity result file for a given dataset ID.

    Args:
        client: MinIO client instance
        bucket: Bucket name
        dataset_id: Dataset identifier to search for

    Returns:
        Tuple of (object_name, parsed_json) if found, None otherwise
    """
    prefix = settings.similarity_result_prefix.strip("/")

    # Construct the expected path for this dataset
    if prefix:
        search_prefix = f"{prefix}/{dataset_id}/"
    else:
        search_prefix = f"{dataset_id}/"

    try:
        objects = client.list_objects(bucket, prefix=search_prefix, recursive=True)

        for obj in objects:
            # Skip directories
            if obj.object_name.endswith("/"):
                continue

            # Only process JSON files
            if not obj.object_name.endswith(".json"):
                continue

            try:
                # Read the similarity result file
                response = client.get_object(bucket, obj.object_name)
                data = response.read()
                response.close()
                response.release_conn()

                # Parse JSON
                parsed = json.loads(data)

                # Verify this is the correct dataset
                if parsed.get("dataset_id") == dataset_id:
                    logger.info("Found similarity result for dataset %s at %s", dataset_id, obj.object_name)
                    return obj.object_name, parsed

            except (json.JSONDecodeError, S3Error) as exc:
                logger.warning("Failed to read similarity result %s: %s", obj.object_name, exc)
                continue

    except S3Error as exc:
        logger.error("Failed to search for dataset %s in %s/%s: %s", dataset_id, bucket, search_prefix, exc)

    return None


def search_similarity_by_dataset_id(client: Minio, bucket: str, dataset_id: str) -> SimilaritySearchResponse:
    """Search for similarity results by dataset ID.

    Args:
        client: MinIO client instance
        bucket: Bucket name
        dataset_id: Dataset identifier to search for

    Returns:
        SimilaritySearchResponse with results or not_found status
    """
    dataset_id = dataset_id.strip()

    if not dataset_id:
        logger.warning("Empty dataset_id provided for search")
        return SimilaritySearchResponse(
            dataset_id="",
            status="invalid",
            match_count=0,
        )

    logger.info("Searching for similarity results for dataset: %s", dataset_id)

    result = _find_similarity_result_for_dataset(client, bucket, dataset_id)

    if result is None:
        logger.info("No similarity results found for dataset %s", dataset_id)
        return SimilaritySearchResponse(
            dataset_id=dataset_id,
            status="not_found",
            match_count=0,
        )

    object_name, parsed = result

    # Extract matches and convert to SimilarityMatch objects
    raw_matches = parsed.get("matches", [])
    matches = []

    for match in raw_matches:
        try:
            matches.append(SimilarityMatch(
                dataset_id=match["dataset_id"],
                similarity_score=match["similarity_score"],
                algorithm=match["algorithm"],
                source_url=match["source_url"],
            ))
        except (KeyError, TypeError) as exc:
            logger.warning("Invalid match format in %s: %s", object_name, exc)
            continue

    logger.info("Found %d matches for dataset %s", len(matches), dataset_id)

    return SimilaritySearchResponse(
        dataset_id=dataset_id,
        status=parsed.get("status", "completed"),
        fingerprint_object=parsed.get("fingerprint_object"),
        source_url=parsed.get("source_url"),
        generated_at=parsed.get("generated_at"),
        matches=matches,
        match_count=len(matches),
    )