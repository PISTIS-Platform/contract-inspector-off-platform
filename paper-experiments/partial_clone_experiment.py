"""Column selection for the precautious / careful / greedy partial clones."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from inspector.real_datasets import REAL_DATA_SOURCES, _load_semicolon_csv, _load_xlsx_flight_data_full, registry_value

WEATHER_UNIT_COLS_BASE = [
    "temperature_mean_c", "felt_temperature_mean_c",
    "precipitation_sum_mm", "wind_max_ms",
    "visibility_max_km", "sunshine_duration_sum_h",
]
WEATHER_UNIT_TARGETS = {
    "temperature_mean_c":      "kelvin",
    "felt_temperature_mean_c": "kelvin",
    "precipitation_sum_mm":    "inch",
    "wind_max_ms":             "mile/hour",
    "visibility_max_km":       "mile",
    "sunshine_duration_sum_h": "second",
}
WEATHER_ID_ANCHORS = ["cell_id"]
WEATHER_PRECAUTIOUS_UNIT_COL_BASE = WEATHER_UNIT_COLS_BASE[0]


def weather_selection() -> dict:
    n_unit = len(WEATHER_UNIT_COLS_BASE)
    half = math.ceil(n_unit / 2)

    precautious_unit = [WEATHER_PRECAUTIOUS_UNIT_COL_BASE]
    careful_unit = WEATHER_UNIT_COLS_BASE[:half]
    greedy_unit = WEATHER_UNIT_COLS_BASE

    return {
        "source": "weather",
        "n_unit_related": n_unit,
        "id_anchors": WEATHER_ID_ANCHORS,
        "precautious": {"cols": WEATHER_ID_ANCHORS + precautious_unit,
                         "n_id": len(WEATHER_ID_ANCHORS), "n_unit": 1},
        "careful": {"cols": WEATHER_ID_ANCHORS + careful_unit,
                    "n_id": len(WEATHER_ID_ANCHORS), "n_unit": half},
        "greedy": {"cols": WEATHER_ID_ANCHORS + greedy_unit,
                   "n_id": len(WEATHER_ID_ANCHORS), "n_unit": n_unit},
    }


def flight_selection(data_dir: Path, sample_size: int = 150, seed: int = 42) -> dict:
    id_anchors = list(registry_value("flight_ops", "id_anchors"))
    precautious_col = registry_value("flight_ops", "precautious_unit_col")
    fp = data_dir / registry_value("flight_ops", "filename")
    df, _ = _load_xlsx_flight_data_full(fp, sample_n=sample_size, seed=seed, keep_all_columns=True)
    tz_cols = [c for c in df.columns if str(df[c].dtype).startswith("datetime64")]
    unit_col = "wingspan_m"
    assert unit_col in df.columns

    unit_related = [c for c in df.columns if c in tz_cols or c == unit_col]
    non_unit = [c for c in df.columns if c not in unit_related]
    assert len(unit_related) == 42 and len(non_unit) == 146, (len(unit_related), len(non_unit))
    if precautious_col not in unit_related:
        raise ValueError(f"precautious_unit_col {precautious_col!r} is not a time or unit column of the flight data "
                         "(see data/sources.toml)")
    for c in id_anchors:
        if c not in non_unit:
            raise ValueError(f"id anchor {c!r} is not a non-time column of the flight data")

    half = math.ceil(len(unit_related) / 2)
    return {
        "source": "flight",
        "n_usable_cols": len(df.columns),
        "n_unit_related": len(unit_related),
        "n_non_unit": len(non_unit),
        "id_anchors": id_anchors,
        "precautious": {"cols": id_anchors + [precautious_col], "n_id": len(id_anchors), "n_unit": 1},
        "careful": {"cols": id_anchors + unit_related[:half], "n_id": len(id_anchors), "n_unit": half},
        "greedy": {"cols": id_anchors + unit_related, "n_id": len(id_anchors), "n_unit": len(unit_related)},
    }


BAGGAGE_NATIVE_ROWS = {
    "arrival_baggage": 12234, "departure_baggage": 14657,
    "transfer_baggage": 53803, "breakdown_baggage": 48347,
}


def baggage_selection(data_dir: Path, seed: int = 42) -> dict:
    out = {}
    for name in ["arrival_baggage", "departure_baggage", "transfer_baggage", "breakdown_baggage"]:
        id_anchors = list(registry_value(name, "id_anchors"))
        precautious_col = registry_value(name, "precautious_ts_col")
        fp = data_dir / REAL_DATA_SOURCES[name]["filename"]
        df = _load_semicolon_csv(fp, sample_n=BAGGAGE_NATIVE_ROWS[name] + 1, seed=seed)
        tz_cols = [c for c in df.columns if str(df[c].dtype).startswith("datetime64")]
        non_tz = [c for c in df.columns if c not in tz_cols]
        if precautious_col not in tz_cols:
            raise ValueError(f"precautious_ts_col {precautious_col!r} is not a timestamp column of {name}")
        for c in id_anchors:
            if c not in non_tz:
                raise ValueError(f"id anchor {c!r} is not a non-time column of {name}")

        half = math.ceil(len(tz_cols) / 2)
        out[name] = {
            "n_cols": len(df.columns),
            "n_ts": len(tz_cols),
            "n_non_ts": len(non_tz),
            "n_rows_loaded": len(df),
            "id_anchors": id_anchors,
            "precautious": {"cols": id_anchors + [precautious_col], "n_id": len(id_anchors), "n_unit": 1},
            "careful": {"cols": id_anchors + tz_cols[:half], "n_id": len(id_anchors), "n_unit": half},
            "greedy": {"cols": id_anchors + tz_cols, "n_id": len(id_anchors), "n_unit": len(tz_cols)},
        }
    return out


def _df_to_dataset_full(df: pd.DataFrame, name: str):
    from inspector.loader import Dataset, Modality
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%dT%H:%M:%S")
    df = df.fillna("")
    return Dataset(data=df.to_dict("records"), modality=Modality.STRUCTURED_CSV,
                    source_path=name)


def _slice_clone(clone, keep_cols: list[str], tag: str):
    from inspector.loader import Dataset
    keep = set(keep_cols)
    data = [{k: v for k, v in rec.items() if k in keep}
            for rec in clone.data if isinstance(rec, dict)]
    sliced_unit_meta = {k: v for k, v in getattr(clone, "unit_meta", {}).items() if k in keep}
    return Dataset(data=data, modality=clone.modality, source_path=clone.source_path + tag,
                   unit_meta=sliced_unit_meta)
