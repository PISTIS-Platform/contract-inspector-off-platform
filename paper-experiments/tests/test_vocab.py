import json
from pathlib import Path

import pytest

pytest.importorskip("pint")

from inspector import timezones as Z
from inspector import units as U
from inspector import vocab
from inspector.vocab import VocabularyError
from inspector.vocab.__main__ import main as cli

BASELINE = json.loads((Path(__file__).parent / "fixtures" / "vocab_baseline.json").read_text())

PSI = """
mode = "extend"
[suffix]
pa  = { unit = "pascal",     canonical = "pascal", dimension = "pressure", alt = "psi" }
kpa = { unit = "kilopascal", canonical = "pascal", dimension = "pressure", alt = "pa" }
psi = { unit = "psi",        canonical = "pascal", dimension = "pressure", alt = "kpa" }
"""


@pytest.fixture(autouse=True)
def restore_default_vocabulary(monkeypatch):
    for var in ("INSPECTOR_UNITS_VOCAB", "INSPECTOR_TZ_VOCAB", "PISTIS_DATA_DIR"):
        monkeypatch.delenv(var, raising=False)
    yield
    U.use_vocabulary(vocab.default_units())
    Z.use_vocabulary(vocab.default_timezones())


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_defaults_match_baseline():
    v = vocab.default_units()
    assert [[k, list(x)] for k, x in v.suffix_map.items()] == BASELINE["SUFFIX_MAP"]
    assert [[k, x] for k, x in v.alt_suffix.items()] == BASELINE["ALT_SUFFIX"]
    assert sorted(v.ambiguous) == BASELINE["AMBIGUOUS_SUFFIXES"]
    assert [[k, list(x)] for k, x in v.dimension_keywords.items()] == BASELINE["DIMENSION_KEYWORDS"]


def test_module_names_populated():
    assert [[k, list(x)] for k, x in U.SUFFIX_MAP.items()] == BASELINE["SUFFIX_MAP"]
    assert [[k, x] for k, x in U.ALT_SUFFIX.items()] == BASELINE["ALT_SUFFIX"]
    assert sorted(U._AMBIGUOUS_SUFFIXES) == BASELINE["AMBIGUOUS_SUFFIXES"]
    assert [[k, list(x)] for k, x in U._DIMENSION_KEYWORDS.items()] == BASELINE["DIMENSION_KEYWORDS"]
    assert [[k, x] for k, x in U._UNIT_TO_CANONICAL.items()] == BASELINE["UNIT_TO_CANONICAL"]
    assert U._CANONICAL_SIG_FIGS == BASELINE["CANONICAL_SIG_FIGS"]


def test_tz_defaults_match_baseline():
    assert str(Z.REFERENCE_TZ) == BASELINE["REFERENCE_TZ"] and str(Z.ALT_TZ) == BASELINE["ALT_TZ"]
    assert (Z._EPOCH_MIN, Z._EPOCH_MAX) == (BASELINE["EPOCH_MIN"], BASELINE["EPOCH_MAX"])
    assert sorted(Z._EPOCH_NAME_KEYWORDS) == BASELINE["EPOCH_NAME_KEYWORDS"]


def test_defaults_valid():
    vocab.validate_units(vocab.default_units())
    vocab.validate_timezones(vocab.default_timezones())


def test_extend(tmp_path):
    v = vocab.load_vocabulary(write(tmp_path, "u.toml", PSI))
    base = list(vocab.default_units().suffix_map)
    assert list(v.suffix_map)[: len(base)] == base and list(v.suffix_map)[-3:] == ["pa", "kpa", "psi"]
    assert v.origin["psi"].endswith("u.toml") and v.origin["c"] == "default"


def test_override_and_remove(tmp_path):
    p = write(tmp_path, "u.toml", 'remove = ["kn"]\n[suffix]\nft = { unit = "foot", canonical = "meter", dimension = "length", alt = "cm" }\n')
    v = vocab.load_vocabulary(p)
    assert "kn" not in v.suffix_map and v.alt_suffix["ft"] == "cm" and v.origin["ft"].endswith("u.toml")
    assert "kn" in vocab.default_units().suffix_map


def test_replace(tmp_path):
    p = write(tmp_path, "u.toml", 'mode = "replace"\n[suffix]\npsi = { unit = "psi", canonical = "pascal", dimension = "pressure" }\n')
    v = vocab.load_vocabulary(p)
    assert list(v.suffix_map) == ["psi"] and not v.ambiguous


def test_keywords(tmp_path):
    v = vocab.load_vocabulary(write(tmp_path, "u.toml", '[dimension.temperature]\nextra_keywords = ["thermo"]\n'))
    assert v.dimension_keywords["temperature"] == ("temp", "thermo")
    v = vocab.load_vocabulary(write(tmp_path, "u2.toml", '[dimension.temperature]\nkeywords = ["thermo"]\n'))
    assert v.dimension_keywords["temperature"] == ("thermo",)


def test_activate(tmp_path):
    ref = U.SUFFIX_MAP
    assert U.split_suffix("tank_pressure_psi") == ("tank_pressure_psi", None)
    vocab.activate(vocab.load_vocabulary(write(tmp_path, "u.toml", PSI)))
    assert ref is U.SUFFIX_MAP and "psi" in ref
    assert U.split_suffix("tank_pressure_psi") == ("tank_pressure", "psi")
    assert U.to_canonical("tank_pressure_psi", 1.0) == ("tank_pressure", pytest.approx(6894.76, rel=1e-5))
    assert U.to_alternative("tank_pressure_kpa", 100.0)[0] == "tank_pressure_pa"


def test_tz_activate(tmp_path):
    p = write(tmp_path, "t.toml", 'reference_tz = "Europe/Berlin"\n[epoch]\nextra_name_keywords = ["logged"]\n')
    v = vocab.load_vocabulary(p)
    assert v.reference_tz == "Europe/Berlin" and "logged" in v.name_keywords and "ibt" in v.name_keywords
    vocab.activate(v)
    assert Z.to_utc("2023-08-01T12:00:00") == "2023-08-01T10:00:00+00:00"


@pytest.mark.parametrize("entry,needle", [
    ('bar = { unit = "barr", canonical = "pascal", dimension = "pressure" }', "pint does not know unit 'barr'"),
    ('bar = { unit = "bar", canonical = "meter", dimension = "pressure" }', "cannot be converted"),
    ('x = { unit = "kilometer", canonical = "meter", dimension = "length" }', "use the same unit"),
    ('c2 = { unit = "degC", canonical = "kelvin", dimension = "temperature" }', "disagree on the canonical unit"),
    ('bar = { unit = "bar", canonical = "pascal", dimension = "pressure", alt = "zz" }', "alt 'zz' is not a defined suffix"),
    ('bar = { unit = "bar", canonical = "pascal", dimension = "pressure", alt = "km" }', "not 'pressure'"),
    ('bar = { unit = "bar", canonical = "pascal", dimension = "pressure", ambiguous = true }', "has no keywords"),
    ('Bar = { unit = "bar", canonical = "pascal", dimension = "pressure" }', "lower-case letters/digits"),
    ('b_r = { unit = "bar", canonical = "pascal", dimension = "pressure" }', "no underscore"),
    ('bar = { unit = "bar", canonical = "pascal", dimension = "pressure", colour = "red" }', "unknown key 'colour'"),
    ('bar = { canonical = "pascal", dimension = "pressure" }', "missing or empty string key 'unit'"),
])
def test_invalid_units(tmp_path, entry, needle):
    with pytest.raises(VocabularyError) as e:
        vocab.load_vocabulary(write(tmp_path, "u.toml", f"[suffix]\n{entry}\n"))
    assert needle in str(e.value)


def test_all_errors_listed(tmp_path):
    p = write(tmp_path, "u.toml", '[suffix]\na1 = { unit = "zzz", canonical = "pascal", dimension = "p" }\n'
                                  'a2 = { unit = "yyy", canonical = "pascal", dimension = "p" }\n')
    with pytest.raises(VocabularyError) as e:
        vocab.load_vocabulary(p)
    assert "2 problem(s)" in str(e.value)


@pytest.mark.parametrize("text,needle", [
    ('reference_tz = "Mars/Olympus"', "not a known time-zone id"),
    ('[epoch]\nmin = 10\nmax = 5', "must be smaller than"),
    ('[epoch]\nextra_name_keywords = ["TS"]', "must be lower-case"),
    ('colour = "red"', "unknown key"),
    ('mode = "merge"', "mode must be"),
])
def test_invalid_timezones(tmp_path, text, needle):
    with pytest.raises(VocabularyError) as e:
        vocab.load_vocabulary(write(tmp_path, "t.toml", text + "\n"), kind="timezones")
    assert needle in str(e.value)


def test_synonym_suffix(tmp_path):
    v = vocab.load_vocabulary(write(tmp_path, "u.toml", '[suffix]\nkph = { unit = "km/h", canonical = "meter/second", dimension = "speed" }\n'))
    vocab.activate(v)
    assert U.to_canonical("wind_kph", 36.0) == ("wind", 10.0)
    assert U._UNIT_TO_CANONICAL["km/h"] == "meter/second"
    assert U.to_canonical("wind_max", 36.0, "km/h") == ("wind_max", 10.0)
    with pytest.raises(VocabularyError, match="use the same unit"):
        vocab.load_vocabulary(write(tmp_path, "d.toml", '[suffix]\nkph = { unit = "kilometer/hour", canonical = "meter/second", dimension = "speed" }\n'))


def test_declared_unit_spelling():
    assert U.to_canonical("t", 20.0, "degC") == ("t", 20.0)
    assert U.to_canonical("t", 20.0, "celsius") is None


def test_bad_files(tmp_path):
    with pytest.raises(VocabularyError, match="cannot remove unknown"):
        vocab.load_vocabulary(write(tmp_path, "u.toml", 'remove = ["nope"]\n[suffix]\n'), kind="units")
    with pytest.raises(VocabularyError, match="not valid TOML"):
        vocab.load_vocabulary(write(tmp_path, "b.toml", "[suffix\n"), kind="units")
    with pytest.raises(VocabularyError, match="not found"):
        vocab.load_vocabulary(tmp_path / "missing.toml", kind="units")


def test_lookup_order(tmp_path, monkeypatch):
    mk = lambda name, s: write(tmp_path, name, f'[suffix]\n{s} = {{ unit = "psi", canonical = "pascal", dimension = "pressure" }}\n')
    explicit, env = mk("e.toml", "xp"), mk("v.toml", "ev")
    data = tmp_path / "data"
    (data / "vocab").mkdir(parents=True)
    (data / "vocab" / "units.toml").write_text('[suffix]\nddd = { unit = "psi", canonical = "pascal", dimension = "pressure" }\n')
    assert "psi" not in [s for s in vocab.active_units().suffix_map if s not in vocab.default_units().suffix_map]
    monkeypatch.setenv("PISTIS_DATA_DIR", str(data))
    assert "ddd" in vocab.active_units().suffix_map
    monkeypatch.setenv("INSPECTOR_UNITS_VOCAB", str(env))
    assert "ev" in vocab.active_units().suffix_map and "ddd" not in vocab.active_units().suffix_map
    v = vocab.load_vocabulary(explicit)
    assert "xp" in v.suffix_map and "ev" not in v.suffix_map
    monkeypatch.setenv("INSPECTOR_UNITS_VOCAB", str(tmp_path / "missing.toml"))
    with pytest.raises(VocabularyError, match="not found"):
        vocab.active_units()


@pytest.mark.parametrize("name", ["temperature_mean_c", "aircraft_class_c", "wind_max_ms", "flight_id", "x", "_c",
                                  "count_s", "sunshine_duration_sum_h", "distance_km", "phase_v", "load_kw"])
def test_explain_field(name):
    assert U.explain_field(name)["detected"] == (U.split_suffix(name)[1] is not None)


def test_explain_column():
    assert Z.explain_column("t", ["2023-08-01T12:00:00+03:00", "2023-08-01T12:10:00"])["kind"] == "iso"
    assert Z.explain_column("t_ibt", ["1690880400"])["kind"] == "epoch"
    assert Z.explain_column("n", ["1", "2"])["kind"] is None


def test_cli(tmp_path, capsys):
    csv_path = write(tmp_path, "d.csv", "tank_pressure_psi,temperature_mean_c,aircraft_class_c,ts\n"
                                        "31.5,20.1,2,1690880400\n32.0,20.4,2,1690881000\n")
    assert cli(["scan", str(csv_path)]) == 0
    out = capsys.readouterr().out
    assert "suffix 'psi' is not in the unit vocabulary" in out
    assert "accepted because 'temperature_mean' contains the temperature keyword 'temp'" in out
    assert "'aircraft_class' contains none of the temperature keywords" in out
    assert "TIMESTAMP (epoch)" in out and "1 unit-bearing and 1 timestamp" in out
    vfile = write(tmp_path, "u.toml", PSI)
    assert cli(["check", str(vfile)]) == 0
    assert "3 added" in capsys.readouterr().out
    assert cli(["check", str(write(tmp_path, "bad.toml", '[suffix]\nz = { unit = "nope", canonical = "meter", dimension = "length" }\n'))]) == 1
    assert "INVALID" in capsys.readouterr().err
    assert cli(["list"]) == 0
    assert "shipped default" in capsys.readouterr().out


def test_cli_scan_env(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("INSPECTOR_UNITS_VOCAB", str(write(tmp_path, "u.toml", PSI)))
    import importlib
    importlib.reload(U)
    try:
        csv_path = write(tmp_path, "d.csv", "tank_pressure_psi\n31.5\n")
        assert cli(["scan", str(csv_path)]) == 0
        assert "UNIT psi -> pascal (pressure)" in capsys.readouterr().out
    finally:
        monkeypatch.delenv("INSPECTOR_UNITS_VOCAB")
        importlib.reload(U)
