"""Search endpoint for retrieving similarity results."""

import logging

from fastapi import APIRouter, HTTPException, Query

from ..config import get_settings
from ..schemas import SimilaritySearchResponse
from ..services.minio_service import get_minio_client
from ..services.similarity_search import search_similarity_by_dataset_id

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()


@router.get("/search", response_model=SimilaritySearchResponse, status_code=200)
def get_similarity_results(
    dataset_id: str = Query(
        ...,
        description="Dataset identifier to search for",
        min_length=1,
    )
) -> SimilaritySearchResponse:
    """Search for similarity results by dataset ID.

    Retrieves the similarity results for a given dataset, including all
    fingerprints that were found to be similar based on the configured
    similarity threshold.

    Args:
        dataset_id: The dataset identifier to search for

    Returns:
        SimilaritySearchResponse with matches or not_found status

    Raises:
        HTTPException: 404 if the dataset is not found
        HTTPException: 400 if dataset_id is invalid
    """
    dataset_id = dataset_id.strip()

    if not dataset_id:
        logger.warning("Empty dataset_id provided to search endpoint")
        raise HTTPException(status_code=400, detail="dataset_id must not be blank")

    logger.info("Search request received for dataset: %s", dataset_id)

    client = get_minio_client(settings)
    bucket = settings.local_minio_bucket

    response = search_similarity_by_dataset_id(client, bucket, dataset_id)

    if response.status == "invalid":
        raise HTTPException(status_code=400, detail="Invalid dataset_id")

    if response.status == "not_found":
        raise HTTPException(
            status_code=404,
            detail=f"No similarity results found for dataset: {dataset_id}"
        )

    logger.info("Returning %d matches for dataset %s", response.match_count, dataset_id)
    return response