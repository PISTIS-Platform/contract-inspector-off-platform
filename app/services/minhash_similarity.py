"""MinHash-based similarity computation for fingerprints."""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class FingerprintData:
    """Represents a parsed fingerprint with its metadata."""

    def __init__(self, fingerprint: list[int], algorithm: str, dataset_id: str, source_url: str):
        """Initialize fingerprint data.

        Args:
            fingerprint: List of MinHash signature values
            algorithm: Algorithm used (adhoc_minhash or datasketch_minhash)
            dataset_id: Dataset identifier
            source_url: Source URL of the fingerprint
        """
        self.fingerprint = fingerprint
        self.algorithm = algorithm
        self.dataset_id = dataset_id
        self.source_url = source_url

    @classmethod
    def from_json(cls, data: bytes, dataset_id: str, source_url: str) -> "FingerprintData":
        """Parse fingerprint from JSON bytes.

        Args:
            data: JSON bytes containing fingerprint data
            dataset_id: Dataset identifier
            source_url: Source URL of the fingerprint

        Returns:
            FingerprintData instance

        Raises:
            ValueError: If JSON is malformed or missing required fields
        """
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in fingerprint: {exc}") from exc

        fingerprint = parsed.get("fingerprint")
        algorithm = parsed.get("algorithm")

        if not isinstance(fingerprint, list):
            raise ValueError(f"Fingerprint must be a list, got {type(fingerprint)}")

        if not algorithm:
            raise ValueError("Missing 'algorithm' field in fingerprint")

        if algorithm not in {"adhoc_minhash", "datasketch_minhash"}:
            logger.warning("Unknown algorithm '%s', proceeding anyway", algorithm)

        return cls(
            fingerprint=fingerprint,
            algorithm=algorithm,
            dataset_id=dataset_id,
            source_url=source_url,
        )


def compute_jaccard_similarity(fingerprint_a: list[int], fingerprint_b: list[int]) -> float:
    """Compute Jaccard similarity estimate from two MinHash signatures.

    The Jaccard similarity is estimated by comparing the proportion of matching
    hash values in the two MinHash signatures.

    Args:
        fingerprint_a: First MinHash signature (list of hash values)
        fingerprint_b: Second MinHash signature (list of hash values)

    Returns:
        Similarity score between 0.0 and 1.0, where 1.0 means identical

    Raises:
        ValueError: If fingerprints have different lengths
    """
    if len(fingerprint_a) != len(fingerprint_b):
        raise ValueError(
            f"Fingerprint length mismatch: {len(fingerprint_a)} != {len(fingerprint_b)}"
        )

    if len(fingerprint_a) == 0:
        return 0.0

    matches = sum(1 for a, b in zip(fingerprint_a, fingerprint_b) if a == b)
    similarity = matches / len(fingerprint_a)

    return similarity


def find_similar_fingerprints(
    target_fingerprint: FingerprintData,
    candidate_fingerprints: list[FingerprintData],
    threshold: float = 0.7,
) -> list[dict[str, Any]]:
    """Find fingerprints similar to the target fingerprint.

    Args:
        target_fingerprint: The fingerprint to compare against
        candidate_fingerprints: List of fingerprints to compare with
        threshold: Minimum similarity score (0.0 to 1.0) to consider a match

    Returns:
        List of match dictionaries, sorted by similarity score (highest first).
        Each match contains:
        - dataset_id: Dataset identifier of the match
        - similarity_score: Jaccard similarity score (0.0 to 1.0)
        - algorithm: Algorithm used for the matched fingerprint
        - source_url: Source URL of the matched fingerprint
    """
    matches = []

    for candidate in candidate_fingerprints:
        # Skip self-comparison
        if candidate.dataset_id == target_fingerprint.dataset_id:
            continue

        # Log warning if algorithms differ
        if candidate.algorithm != target_fingerprint.algorithm:
            logger.warning(
                "Comparing fingerprints with different algorithms: %s vs %s (datasets %s, %s)",
                target_fingerprint.algorithm,
                candidate.algorithm,
                target_fingerprint.dataset_id,
                candidate.dataset_id,
            )

        try:
            similarity = compute_jaccard_similarity(
                target_fingerprint.fingerprint,
                candidate.fingerprint,
            )

            if similarity >= threshold:
                matches.append(
                    {
                        "dataset_id": candidate.dataset_id,
                        "similarity_score": round(similarity, 4),
                        "algorithm": candidate.algorithm,
                        "source_url": candidate.source_url,
                    }
                )
        except ValueError as exc:
            logger.error(
                "Failed to compare fingerprints for datasets %s and %s: %s",
                target_fingerprint.dataset_id,
                candidate.dataset_id,
                exc,
            )
            continue

    # Sort by similarity score (highest first)
    matches.sort(key=lambda m: m["similarity_score"], reverse=True)

    return matches