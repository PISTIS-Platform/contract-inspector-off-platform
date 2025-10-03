"""Similarity endpoints."""

from fastapi import APIRouter

from ..schemas import FingerprintSimilarityRequest, FingerprintSimilarityResponse
from ..services import acknowledge_similarity_request

router = APIRouter()


@router.post("/similarity", response_model=FingerprintSimilarityResponse, status_code=202)
def similarity(request: FingerprintSimilarityRequest) -> FingerprintSimilarityResponse:
    return acknowledge_similarity_request(request)
