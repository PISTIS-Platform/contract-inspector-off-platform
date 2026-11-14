"""Loaders for the real flight, baggage and weather data."""

import re
from pathlib import Path

import numpy as np
import pandas as pd

from .loader import Dataset, Modality


def _load_real_data_sources() -> dict[str, dict]:
    import os
    import tomllib

    root = Path(__file__).resolve().parents[1]
    env = os.environ.get("PISTIS_SOURCES_CONFIG")
    if env:
        path = Path(env)
        if not path.is_file():
            raise FileNotFoundError(f"PISTIS_SOURCES_CONFIG points to a file that does not exist: {path}")
    else:
        path = root / "data" / "sources.toml"
        if not path.is_file():
            path = root / "data" / "sources.example.toml"
    global REGISTRY_PATH
    REGISTRY_PATH = path
    with open(path, "rb") as f:
        return {name: dict(entry) for name, entry in tomllib.load(f).items()}


REGISTRY_PATH: Path = Path("data/sources.example.toml")
REAL_DATA_SOURCES: dict[str, dict] = _load_real_data_sources()


class SourceRegistryError(LookupError):
    pass


def registry_value(source: str, key: str):
    section = REAL_DATA_SOURCES.get(source)
    if section is None:
        raise SourceRegistryError(f"{REGISTRY_PATH} has no [{source}] section")
    if key not in section:
        raise SourceRegistryError(f"{REGISTRY_PATH}: section [{source}] has no key {key!r}")
    return section[key]


WEATHER_VARIABLES: dict[str, str] = {
    "temperature_mean": "temperature_mean_c",
    "felt_temperature_mean": "felt_temperature_mean_c",
    "precipitation_sum": "precipitation_sum_mm",
    "wind_max": "wind_max_ms",
    "visibility_max": "visibility_max_km",
    "sunshine_duration_sum": "sunshine_duration_sum_h",
}


def _index_weather_days(raster_dir: Path) -> dict[str, dict[str, Path]]:
    by_date: dict[str, dict[str, Path]] = {}
    for path in raster_dir.glob("*.tiff"):
        m = re.match(r"(.+)_(\d{8})$", path.stem)
        if not m:
            continue
        var, date = m.group(1), m.group(2)
        if var in WEATHER_VARIABLES:
            by_date.setdefault(date, {})[var] = path
    return {d: v for d, v in by_date.items() if len(v) == len(WEATHER_VARIABLES)}


def _weather_day_to_dataset(date: str, var_paths: dict[str, Path],
                            cell_idx: np.ndarray, name: str) -> Dataset:
    import tifffile

    columns: dict[str, np.ndarray] = {}
    for var, column in WEATHER_VARIABLES.items():
        arr = np.asarray(tifffile.imread(var_paths[var]), dtype=np.float64).ravel()
        columns[column] = arr[cell_idx]

    records = []
    for i, flat in enumerate(cell_idx):
        rec = {"cell_id": f"c{int(flat)}", "obs_date": date}
        for var, column in WEATHER_VARIABLES.items():
            val = float(columns[column][i])
            rec[column] = round(val, 3)
        records.append(rec)
    return Dataset(data=records, modality=Modality.STRUCTURED_CSV, source_path=name)


def load_weather_days(raster_dir: Path, n_days: int, n_cells: int, seed: int,
                      all_days: bool = False, all_cells: bool = False) -> list[Dataset]:
    """Load weather snapshots as tabular Datasets sharing a fixed cell sample."""
    days = _index_weather_days(raster_dir)
    if not days:
        return []
    dates = sorted(days)
    if not all_days and n_days < len(dates):
        step = len(dates) / n_days
        dates = [dates[int(i * step)] for i in range(n_days)]

    sample_var = next(iter(WEATHER_VARIABLES))
    import tifffile
    shape = tifffile.imread(days[dates[0]][sample_var]).shape
    n_total = int(np.prod(shape))
    if all_cells:
        cell_idx = np.arange(n_total)
    else:
        rng = np.random.default_rng(seed)
        cell_idx = np.sort(rng.choice(n_total, size=min(n_cells, n_total), replace=False))

    return [
        _weather_day_to_dataset(d, days[d], cell_idx, name=f"real/weather_window_w{i}")
        for i, d in enumerate(dates)
    ]


def _load_xlsx_flight_data_full(
    filepath: Path,
    sample_n: int,
    seed: int,
    keep_all_columns: bool = False,
) -> tuple[pd.DataFrame, dict]:
    df = pd.read_excel(filepath, engine="openpyxl")
    df.columns = df.columns.str.strip()
    total_cols_raw = len(df.columns)
    total_rows = len(df)

    if not keep_all_columns:
        df = df.dropna(axis=1, how="all")
    usable_cols = len(df.columns)
    dropped_empty = total_cols_raw - usable_cols

    if "Wingspan" in df.columns:
        df = df.rename(columns={"Wingspan": "wingspan_m"})

    tz_bearing = [c for c in df.columns
                  if pd.api.types.is_datetime64_any_dtype(df[c])]
    tz_bearing_cols = len(tz_bearing)

    from .units import split_suffix
    unit_bearing = [c for c in df.columns
                    if split_suffix(c.lower().replace(" ", "_"))[1] is not None]
    unit_bearing_cols = len(unit_bearing)

    if len(df) > sample_n:
        df = df.sample(n=sample_n, random_state=seed)

    meta = {
        "total_cols_raw": total_cols_raw,
        "dropped_empty": dropped_empty,
        "usable_cols": usable_cols,
        "tz_bearing_cols": tz_bearing_cols,
        "unit_bearing_cols": unit_bearing_cols,
        "total_rows": total_rows,
    }
    return df.reset_index(drop=True), meta


def _load_semicolon_csv(
    filepath: Path,
    sample_n: int,
    seed: int,
) -> pd.DataFrame:
    try:
        df = pd.read_csv(filepath, sep=";", encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(filepath, sep=";", encoding="latin-1")

    df.columns = df.columns.str.strip()
    df = df.dropna(axis=1, how="all")

    if len(df) > sample_n:
        df = df.sample(n=sample_n, random_state=seed)

    for col in df.select_dtypes(include="object").columns:
        s = df[col].dropna().astype(str)
        if len(s) and s.str.contains(":").mean() > 0.8:
            parsed = pd.to_datetime(df[col], dayfirst=True, errors="coerce")
            if parsed.notna().mean() > 0.8:
                df[col] = parsed

    return df.reset_index(drop=True)


def _df_to_dataset(
    df: pd.DataFrame,
    name: str,
    modality: Modality = Modality.STRUCTURED_CSV,
) -> Dataset:
    df = df.copy()

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%dT%H:%M:%S")

    df = df.fillna("")

    data = df.to_dict("records")
    return Dataset(data=data, modality=modality, source_path=name)
