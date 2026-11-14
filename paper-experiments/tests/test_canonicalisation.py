import pytest

pytest.importorskip("pint")

from inspector import timezones as Z
from inspector import units as U
from inspector.loader import Dataset, Modality

M = Modality.STRUCTURED_CSV


def test_suffix_units_converge_to_canonical():
    assert U.to_canonical("temperature_mean_c", 20) == ("temperature_mean", 20.0)
    assert U.to_canonical("temperature_mean_f", 68) == ("temperature_mean", 20.0)
    assert U.to_canonical("temperature_mean_k", 293.15) == ("temperature_mean", 20.0)
    for f, v in (("wind_max_ms", 10), ("wind_max_kmh", 36)):
        assert U.to_canonical(f, v) == ("wind_max", 10.0)


def test_ambiguous_single_letter_suffix_needs_a_matching_name():
    assert U.to_canonical("c", 5) is None
    assert U.to_canonical("count_c", 5) is None
    assert U.to_canonical("temperature_mean_c", 5) is not None


def test_declared_unit_takes_precedence_over_name():
    assert U.to_canonical("precip", 1.0, declared_unit="inch") == ("precip", pytest.approx(0.0254))


def test_utc_canonicalisation_iso_and_epoch():
    iso = Z.to_utc("2023-08-01T12:00:00+03:00")
    assert iso == "2023-08-01T09:00:00+00:00"
    assert Z.to_epoch("2023-08-01T12:00:00+03:00") == 1690880400
    assert Z.epoch_to_utc(1690880400) == iso


def test_value_only_clone_normalises_to_the_source():
    base = Dataset(data=[{"id": 1, "temperature_mean_c": 20.0, "ts": "2023-08-01T12:00:00+03:00"},
                         {"id": 2, "temperature_mean_c": -5.5, "ts": "2023-08-02T00:30:00+03:00"}],
                   modality=M, source_path="base")
    clone = Dataset(data=[{"id": 1, "temperature_mean_c": 68.0, "ts": 1690880400},
                          {"id": 2, "temperature_mean_c": 22.1, "ts": 1690925400}],
                    modality=M, source_path="clone", unit_meta={"temperature_mean_c": "degF"})
    norm = lambda d: Z.normalize_timezones_dataset(U.normalize_dataset(d)).data
    assert norm(base) == norm(clone)
    assert U.count_unit_bearing_fields(base) == 1
    assert Z.count_timezone_bearing_fields(clone) == 1
