"""Pydantic models used by the similarity API."""

from typing import Any, Optional
from pydantic import AnyUrl, BaseModel, Field, model_validator


class FingerprintSimilarityRequest(BaseModel):
    fingerprint_url: Optional[AnyUrl] = Field(
        None, description="Presigned URL pointing to the remote fingerprint object."
    )
    fingerprint: Optional[dict[str, Any]] = Field(
        None,
        description="Inline fingerprint payload containing 'fingerprint' (list) and 'algorithm' (string).",
    )
    source_url: Optional[str] = Field(
        None,
        description="Original source URL of the fingerprint when submitted inline.",
    )
    dataset_id: str = Field(
        ..., description="Dataset identifier associated with the fingerprint payload.",
        min_length=1,
    )

    @model_validator(mode="after")
    def _require_exactly_one_source(self) -> "FingerprintSimilarityRequest":
        has_inline = self.fingerprint is not None
        has_url = self.fingerprint_url is not None
        if has_inline == has_url:
            raise ValueError(
                "Exactly one of 'fingerprint' or 'fingerprint_url' must be provided"
            )
        if has_inline:
            fingerprint_values = self.fingerprint.get("fingerprint")
            algorithm = self.fingerprint.get("algorithm")
            if not isinstance(fingerprint_values, list):
                raise ValueError("fingerprint['fingerprint'] must be a list")
            if not isinstance(algorithm, str):
                raise ValueError("fingerprint['algorithm'] must be a string")
        return self


class FingerprintSimilarityResponse(BaseModel):
    dataset_id: str = Field(..., description="Dataset identifier acknowledged by the service.")
    fingerprint_url: Optional[AnyUrl] = Field(
        None, description="Fingerprint URL that was validated, if the request used the URL path."
    )
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
