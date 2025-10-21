"""Pydantic models used by the similarity API."""

from typing import Optional
from pydantic import AnyUrl, BaseModel, Field


class FingerprintSimilarityRequest(BaseModel):
    fingerprint_url: AnyUrl = Field(
        ..., description="Presigned URL pointing to the remote fingerprint object."
    )
    dataset_id: str = Field(
        ..., description="Dataset identifier associated with the fingerprint payload.",
        min_length=1,
    )


class FingerprintSimilarityResponse(BaseModel):
    dataset_id: str = Field(..., description="Dataset identifier acknowledged by the service.")
    fingerprint_url: AnyUrl = Field(..., description="Fingerprint URL that was validated.")
    status: str = Field(..., description="Current processing state of the similarity request.")
    remote_object_available: bool = Field(
        ..., description="Whether the provided URL could be reached successfully."
    )


class SimilarityMatch(BaseModel):
    """A single similarity match result."""
    dataset_id: str = Field(..., description="Dataset identifier of the similar fingerprint.")
    similarity_score: float = Field(..., description="Jaccard similarity score (0.0 to 1.0).")
    algorithm: str = Field(..., description="MinHash algorithm used for the fingerprint.")
    source_url: str = Field(..., description="Original source URL of the matched fingerprint.")


class SimilaritySearchResponse(BaseModel):
    """Response for similarity search query."""
    dataset_id: str = Field(..., description="The dataset identifier that was searched.")
    status: str = Field(..., description="Status of the similarity result (e.g., 'completed', 'processing', 'not_found').")
    fingerprint_object: Optional[str] = Field(None, description="MinIO object path of the fingerprint.")
    source_url: Optional[str] = Field(None, description="Original source URL of the fingerprint.")
    generated_at: Optional[str] = Field(None, description="ISO 8601 timestamp when the result was generated.")
    matches: list[SimilarityMatch] = Field(default_factory=list, description="List of similar fingerprints found.")
    match_count: int = Field(..., description="Total number of matches found.")
