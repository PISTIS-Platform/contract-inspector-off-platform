"""Pydantic models used by the similarity API."""

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
