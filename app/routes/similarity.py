"""Similarity endpoints."""

import logging

from fastapi import APIRouter

from ..schemas import FingerprintSimilarityRequest, FingerprintSimilarityResponse
from ..services import acknowledge_similarity_request

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/similarity", response_model=FingerprintSimilarityResponse, status_code=202)
def similarity(request: FingerprintSimilarityRequest) -> FingerprintSimilarityResponse:
    dataset_id = request.dataset_id.strip()
    logger.info("Accepting similarity request for dataset %s", dataset_id or "<blank>")

    response = acknowledge_similarity_request(request)

    logger.info(
        "Similarity request for dataset %s handled with status %s",
        response.dataset_id,
        response.status,
    )
    return response
