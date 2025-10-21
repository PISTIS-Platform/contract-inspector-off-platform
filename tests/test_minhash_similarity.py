"""Tests for MinHash similarity computation."""

import json
import pytest

from app.services.minhash_similarity import (
    FingerprintData,
    compute_jaccard_similarity,
    find_similar_fingerprints,
)


class TestFingerprintData:
    """Tests for FingerprintData class."""

    def test_from_json_adhoc_minhash(self):
        """Test parsing adhoc_minhash fingerprint from JSON."""
        json_data = json.dumps({
            "fingerprint": [100, 200, 300, 400],
            "algorithm": "adhoc_minhash",
            "dataset_id": "test-dataset",
        }).encode("utf-8")

        fp = FingerprintData.from_json(
            json_data,
            dataset_id="override-dataset",
            source_url="http://example.com/test.csv"
        )

        assert fp.fingerprint == [100, 200, 300, 400]
        assert fp.algorithm == "adhoc_minhash"
        assert fp.dataset_id == "override-dataset"
        assert fp.source_url == "http://example.com/test.csv"

    def test_from_json_datasketch_minhash(self):
        """Test parsing datasketch_minhash fingerprint from JSON."""
        json_data = json.dumps({
            "fingerprint": [111, 222, 333],
            "algorithm": "datasketch_minhash",
        }).encode("utf-8")

        fp = FingerprintData.from_json(
            json_data,
            dataset_id="ds-123",
            source_url="http://example.com/data.csv"
        )

        assert fp.fingerprint == [111, 222, 333]
        assert fp.algorithm == "datasketch_minhash"

    def test_from_json_invalid_json(self):
        """Test parsing invalid JSON raises ValueError."""
        with pytest.raises(ValueError, match="Invalid JSON"):
            FingerprintData.from_json(
                b"not valid json",
                dataset_id="test",
                source_url="http://example.com/test.csv"
            )

    def test_from_json_missing_fingerprint(self):
        """Test parsing JSON without fingerprint field raises ValueError."""
        json_data = json.dumps({
            "algorithm": "adhoc_minhash",
        }).encode("utf-8")

        with pytest.raises(ValueError, match="Fingerprint must be a list"):
            FingerprintData.from_json(
                json_data,
                dataset_id="test",
                source_url="http://example.com/test.csv"
            )

    def test_from_json_missing_algorithm(self):
        """Test parsing JSON without algorithm field raises ValueError."""
        json_data = json.dumps({
            "fingerprint": [1, 2, 3],
        }).encode("utf-8")

        with pytest.raises(ValueError, match="Missing 'algorithm' field"):
            FingerprintData.from_json(
                json_data,
                dataset_id="test",
                source_url="http://example.com/test.csv"
            )


class TestComputeJaccardSimilarity:
    """Tests for Jaccard similarity computation."""

    def test_identical_fingerprints(self):
        """Test that identical fingerprints have similarity 1.0."""
        fp1 = [100, 200, 300, 400, 500]
        fp2 = [100, 200, 300, 400, 500]

        similarity = compute_jaccard_similarity(fp1, fp2)
        assert similarity == 1.0

    def test_completely_different_fingerprints(self):
        """Test that completely different fingerprints have similarity 0.0."""
        fp1 = [100, 200, 300, 400, 500]
        fp2 = [111, 222, 333, 444, 555]

        similarity = compute_jaccard_similarity(fp1, fp2)
        assert similarity == 0.0

    def test_partially_matching_fingerprints(self):
        """Test partial match fingerprints."""
        fp1 = [100, 200, 300, 400, 500]
        fp2 = [100, 200, 333, 444, 555]  # 2 out of 5 match

        similarity = compute_jaccard_similarity(fp1, fp2)
        assert similarity == 0.4  # 2/5 = 0.4

    def test_realistic_minhash_128_high_similarity(self):
        """Test realistic 128-element MinHash with high similarity."""
        # Create two fingerprints with 90% overlap (115 matching, 13 different)
        fp1 = list(range(128))
        fp2 = list(range(128))
        # Change last 13 values
        for i in range(115, 128):
            fp2[i] = fp2[i] + 1000

        similarity = compute_jaccard_similarity(fp1, fp2)
        assert abs(similarity - 115/128) < 0.001  # ~0.8984

    def test_realistic_minhash_128_medium_similarity(self):
        """Test realistic 128-element MinHash with medium similarity."""
        # Create two fingerprints with 70% overlap
        fp1 = list(range(128))
        fp2 = list(range(128))
        # Change last 38 values (keep 90 the same)
        for i in range(90, 128):
            fp2[i] = fp2[i] + 1000

        similarity = compute_jaccard_similarity(fp1, fp2)
        assert abs(similarity - 90/128) < 0.001  # ~0.703

    def test_length_mismatch_raises_error(self):
        """Test that fingerprints of different lengths raise ValueError."""
        fp1 = [100, 200, 300]
        fp2 = [100, 200, 300, 400, 500]

        with pytest.raises(ValueError, match="Fingerprint length mismatch"):
            compute_jaccard_similarity(fp1, fp2)

    def test_empty_fingerprints(self):
        """Test that empty fingerprints return 0.0 similarity."""
        fp1 = []
        fp2 = []

        similarity = compute_jaccard_similarity(fp1, fp2)
        assert similarity == 0.0


class TestFindSimilarFingerprints:
    """Tests for finding similar fingerprints."""

    def test_find_similar_above_threshold(self):
        """Test finding fingerprints above similarity threshold."""
        target = FingerprintData(
            fingerprint=[100, 200, 300, 400, 500],
            algorithm="adhoc_minhash",
            dataset_id="target",
            source_url="http://example.com/target.csv"
        )

        candidates = [
            FingerprintData(
                fingerprint=[100, 200, 300, 400, 500],  # 100% match
                algorithm="adhoc_minhash",
                dataset_id="candidate1",
                source_url="http://example.com/c1.csv"
            ),
            FingerprintData(
                fingerprint=[100, 200, 300, 444, 555],  # 60% match
                algorithm="adhoc_minhash",
                dataset_id="candidate2",
                source_url="http://example.com/c2.csv"
            ),
            FingerprintData(
                fingerprint=[100, 200, 300, 400, 555],  # 80% match
                algorithm="adhoc_minhash",
                dataset_id="candidate3",
                source_url="http://example.com/c3.csv"
            ),
        ]

        matches = find_similar_fingerprints(target, candidates, threshold=0.7)

        # Should find candidate1 (1.0) and candidate3 (0.8), not candidate2 (0.6)
        assert len(matches) == 2
        assert matches[0]["dataset_id"] == "candidate1"
        assert matches[0]["similarity_score"] == 1.0
        assert matches[1]["dataset_id"] == "candidate3"
        assert matches[1]["similarity_score"] == 0.8

    def test_self_comparison_excluded(self):
        """Test that self-comparison is excluded from matches."""
        target = FingerprintData(
            fingerprint=[100, 200, 300],
            algorithm="adhoc_minhash",
            dataset_id="same-id",
            source_url="http://example.com/target.csv"
        )

        candidates = [
            FingerprintData(
                fingerprint=[100, 200, 300],  # Identical but same dataset_id
                algorithm="adhoc_minhash",
                dataset_id="same-id",
                source_url="http://example.com/same.csv"
            ),
            FingerprintData(
                fingerprint=[100, 200, 300],  # Different dataset_id
                algorithm="adhoc_minhash",
                dataset_id="different-id",
                source_url="http://example.com/diff.csv"
            ),
        ]

        matches = find_similar_fingerprints(target, candidates, threshold=0.7)

        # Should only match the one with different dataset_id
        assert len(matches) == 1
        assert matches[0]["dataset_id"] == "different-id"

    def test_sorted_by_similarity_descending(self):
        """Test that matches are sorted by similarity score (highest first)."""
        target = FingerprintData(
            fingerprint=[100, 200, 300, 400, 500],
            algorithm="adhoc_minhash",
            dataset_id="target",
            source_url="http://example.com/target.csv"
        )

        candidates = [
            FingerprintData(
                fingerprint=[100, 200, 300, 444, 555],  # 60% match
                algorithm="adhoc_minhash",
                dataset_id="low",
                source_url="http://example.com/low.csv"
            ),
            FingerprintData(
                fingerprint=[100, 200, 300, 400, 500],  # 100% match
                algorithm="adhoc_minhash",
                dataset_id="high",
                source_url="http://example.com/high.csv"
            ),
            FingerprintData(
                fingerprint=[100, 200, 300, 400, 555],  # 80% match
                algorithm="adhoc_minhash",
                dataset_id="medium",
                source_url="http://example.com/medium.csv"
            ),
        ]

        matches = find_similar_fingerprints(target, candidates, threshold=0.5)

        # Should be sorted: high (1.0), medium (0.8), low (0.6)
        assert len(matches) == 3
        assert matches[0]["dataset_id"] == "high"
        assert matches[0]["similarity_score"] == 1.0
        assert matches[1]["dataset_id"] == "medium"
        assert matches[1]["similarity_score"] == 0.8
        assert matches[2]["dataset_id"] == "low"
        assert matches[2]["similarity_score"] == 0.6

    def test_no_matches_below_threshold(self):
        """Test that no matches are returned when all below threshold."""
        target = FingerprintData(
            fingerprint=[100, 200, 300, 400, 500],
            algorithm="adhoc_minhash",
            dataset_id="target",
            source_url="http://example.com/target.csv"
        )

        candidates = [
            FingerprintData(
                fingerprint=[111, 222, 333, 444, 555],  # 0% match
                algorithm="adhoc_minhash",
                dataset_id="candidate1",
                source_url="http://example.com/c1.csv"
            ),
        ]

        matches = find_similar_fingerprints(target, candidates, threshold=0.7)

        assert len(matches) == 0

    def test_match_includes_all_fields(self):
        """Test that match dict includes all required fields."""
        target = FingerprintData(
            fingerprint=[100, 200, 300],
            algorithm="adhoc_minhash",
            dataset_id="target",
            source_url="http://example.com/target.csv"
        )

        candidates = [
            FingerprintData(
                fingerprint=[100, 200, 300],
                algorithm="datasketch_minhash",
                dataset_id="match",
                source_url="http://example.com/match.csv"
            ),
        ]

        matches = find_similar_fingerprints(target, candidates, threshold=0.5)

        assert len(matches) == 1
        match = matches[0]
        assert "dataset_id" in match
        assert "similarity_score" in match
        assert "algorithm" in match
        assert "source_url" in match
        assert match["dataset_id"] == "match"
        assert match["algorithm"] == "datasketch_minhash"
        assert match["source_url"] == "http://example.com/match.csv"

    def test_length_mismatch_skipped_with_log(self):
        """Test that fingerprints with length mismatch are skipped."""
        target = FingerprintData(
            fingerprint=[100, 200, 300],
            algorithm="adhoc_minhash",
            dataset_id="target",
            source_url="http://example.com/target.csv"
        )

        candidates = [
            FingerprintData(
                fingerprint=[100, 200, 300, 400, 500],  # Wrong length
                algorithm="adhoc_minhash",
                dataset_id="wrong-length",
                source_url="http://example.com/wrong.csv"
            ),
            FingerprintData(
                fingerprint=[100, 200, 300],  # Correct length
                algorithm="adhoc_minhash",
                dataset_id="correct",
                source_url="http://example.com/correct.csv"
            ),
        ]

        matches = find_similar_fingerprints(target, candidates, threshold=0.5)

        # Should only match the one with correct length
        assert len(matches) == 1
        assert matches[0]["dataset_id"] == "correct"
