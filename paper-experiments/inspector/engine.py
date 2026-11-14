"""Scorer interface and backend resolution for the experiment harness."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .loader import Dataset

MISSING_ENGINE = "the similarity engine (inspector/similarity.py) is not installed; re-scoring needs it"


class EngineUnavailable(RuntimeError):
    """Raised when scoring is requested but the private engine is absent."""


@runtime_checkable
class ScoreReport(Protocol):
    """Per-pair result fields read by the harness."""

    jaccard_score: float
    value_score: float
    combined_score: float
    embedding_score: float
    schema_recall: float
    gated_reuse: float
    final_score: float
    method_used: str
    stage_timings: dict[str, float]
    field_similarities: dict[str, float]
    shared_paths: list[str]


@runtime_checkable
class ScorerProtocol(Protocol):
    """A dataset-pair scorer."""

    def compare(self, a: Dataset, b: Dataset) -> ScoreReport: ...


try:
    from .similarity import (
        SimilarityPipeline,
        compute_hash_fingerprint,
        select_best_device,
    )

    ENGINE_AVAILABLE = True
except ImportError:
    ENGINE_AVAILABLE = False

    class SimilarityPipeline:
        """Placeholder: construction raises :class:`EngineUnavailable`."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise EngineUnavailable(MISSING_ENGINE)

    def compute_hash_fingerprint(dataset: Dataset) -> str:
        """SHA-256 of the dataset's serialised content (same value as the engine's fingerprint).

        Runs store its first 16 hex digits as base_sha / clone_sha.
        """
        import hashlib

        from .preprocessing import dataset_to_text

        return hashlib.sha256(dataset_to_text(dataset).encode("utf-8")).hexdigest()

    def select_best_device() -> str:
        return "engine-unavailable"

