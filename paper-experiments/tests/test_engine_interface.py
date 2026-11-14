import pytest

from inspector import engine


def test_imports_without_engine():
    assert hasattr(engine, "SimilarityPipeline") and hasattr(engine, "ScorerProtocol")


@pytest.mark.skipif(engine.ENGINE_AVAILABLE, reason="private engine present")
def test_scoring_needs_engine():
    with pytest.raises(engine.EngineUnavailable, match="similarity engine"):
        engine.SimilarityPipeline(alpha=0.5)


def test_fingerprint():
    import hashlib

    from inspector.loader import Dataset, Modality
    from inspector.preprocessing import dataset_to_text

    ds = Dataset(data=[{"a": 1.5, "b": "x"}, {"a": None, "b": " y "}], modality=Modality.STRUCTURED_CSV, source_path="t")
    expect = hashlib.sha256(dataset_to_text(ds).encode("utf-8")).hexdigest()
    assert engine.compute_hash_fingerprint(ds) == expect and len(expect) == 64


def test_no_engine_files():
    from pathlib import Path

    pkg = Path(engine.__file__).parent
    if engine.ENGINE_AVAILABLE:
        pytest.skip("private engine present locally")
    for name in ("similarity.py", "adaptive.py", "privacy.py", "datasets.py"):
        assert not (pkg / name).exists()
