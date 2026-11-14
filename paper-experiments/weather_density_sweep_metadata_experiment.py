#!/usr/bin/env python3
"""Weather density sweep: convert 1, 3 or 6 of the six unit columns (values only, units declared in metadata)."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import time
from pathlib import Path

from inspector import vocab
from inspector.loader import Dataset
from inspector.persistence import save_dataset, write_manifest
from inspector.provenance import make_timestamped_output_dir
from inspector.real_datasets import REAL_DATA_SOURCES, load_weather_days
from inspector.engine import SimilarityPipeline
from inspector.units import _as_number, _convert
from inspector.vocab._common import default_data_dir

from partial_clone_experiment import WEATHER_UNIT_TARGETS

TAU = 0.5
SEED = 42

UNIT_COLS_NATIVE_ORDER = [
    "temperature_mean_c", "felt_temperature_mean_c", "precipitation_sum_mm",
    "wind_max_ms", "visibility_max_km", "sunshine_duration_sum_h",
]

DENSITY_SCENARIOS: dict[str, list[str]] = {
    "density_1_of_6": UNIT_COLS_NATIVE_ORDER[:1],
    "density_3_of_6": UNIT_COLS_NATIVE_ORDER[:3],
    "density_6_of_6": UNIT_COLS_NATIVE_ORDER[:6],
}


def convert_weather_value_only_metadata(dataset: Dataset, cols_to_convert: list[str]) -> Dataset:
    """Value-only, metadata-truthful conversion of ONLY ``cols_to_convert``."""
    new_meta: dict[str, str] = {}
    convert_set = set(cols_to_convert)

    def _convert_record(rec: dict) -> dict:
        out = {}
        for k, v in rec.items():
            if k in convert_set:
                num = _as_number(v)
                src, dst = WEATHER_UNIT_TARGETS_SRC[k], WEATHER_UNIT_TARGETS[k]
                out[k] = _convert(num, src, dst) if num is not None else v
            else:
                out[k] = v
        return out

    data = [_convert_record(r) if isinstance(r, dict) else copy.deepcopy(r) for r in dataset.data]
    for k in cols_to_convert:
        new_meta[k] = WEATHER_UNIT_TARGETS[k]
    return Dataset(data=data, modality=dataset.modality,
                   source_path=dataset.source_path + ".density_sweep_meta",
                   unit_meta=new_meta)


WEATHER_UNIT_TARGETS_SRC: dict[str, str] = {
    "temperature_mean_c": "degC",
    "felt_temperature_mean_c": "degC",
    "precipitation_sum_mm": "millimeter",
    "wind_max_ms": "meter/second",
    "visibility_max_km": "kilometer",
    "sunshine_duration_sum_h": "hour",
}


def _light_provenance(out: Path, argv: list[str]) -> None:
    prov = out / "provenance"
    prov.mkdir(parents=True, exist_ok=True)
    (prov / "args.json").write_text(json.dumps({"argv": argv}, indent=2))
    try:
        git_head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                   text=True, timeout=5, cwd=Path(__file__).parent).stdout.strip()
        git_status = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                                     text=True, timeout=5, cwd=Path(__file__).parent).stdout
    except Exception as e:
        git_head, git_status = None, str(e)
    (prov / "git.json").write_text(json.dumps({"head": git_head, "dirty_files": git_status}, indent=2))


def main() -> Path:
    vocab.announce()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=default_data_dir())
    ap.add_argument("--weather-days", type=int, default=5)
    ap.add_argument("--weather-cells", type=int, default=5000)
    args = ap.parse_args()

    implementation_root = Path(__file__).resolve().parent
    out = make_timestamped_output_dir(implementation_root / "experiments" / "weather_density_sweep_metadata")
    out.mkdir(parents=True, exist_ok=True)
    datasets_dir = out / "datasets"
    print(out)

    t_start = time.time()

    pipe_off = SimilarityPipeline(alpha=0.5, threshold=TAU)
    pipe_on = SimilarityPipeline(alpha=0.5, threshold=TAU,
                                  normalize_units=True, normalize_timezones=True)

    rdir = args.data_dir / REAL_DATA_SOURCES["weather"]["dirname"]
    print(f"loading {args.weather_days} days x {args.weather_cells} cells (seed {SEED})")
    days = load_weather_days(rdir, n_days=args.weather_days, n_cells=args.weather_cells, seed=SEED)
    assert len(days) == args.weather_days
    n_cols_base = len(days[0].data[0])
    assert n_cols_base == 8, f"expected 8-col weather schema, got {n_cols_base}"
    print(f"{len(days)} days, {len(days[0].data)} cells/day, {n_cols_base} columns")

    warm_clone = convert_weather_value_only_metadata(days[0], DENSITY_SCENARIOS["density_3_of_6"])
    _ = pipe_off.compare(days[0], warm_clone)
    _ = pipe_on.compare(days[0], warm_clone)

    rows: list[dict] = []
    for scenario, cols in DENSITY_SCENARIOS.items():
        density = len(cols) / len(UNIT_COLS_NATIVE_ORDER)
        density_of_schema = len(cols) / n_cols_base
        for i, base in enumerate(days):
            clone = convert_weather_value_only_metadata(base, cols)
            clone.source_path = f"real/weather_density_{scenario}_d{i:02d}"
            if i == 0:
                save_dataset(base, datasets_dir)
                save_dataset(clone, datasets_dir)

            roff = pipe_off.compare(base, clone).to_dict()
            ron = pipe_on.compare(base, clone).to_dict()
            row = {
                "scenario": scenario, "n_cols_converted": len(cols), "n_unit_cols": len(UNIT_COLS_NATIVE_ORDER),
                "density_of_unit_cols": density, "density_of_schema": density_of_schema,
                "day": f"day_{i:02d}",
                "jaccard_off": roff["jaccard_score"], "value_off": roff["value_score"],
                "combined_off": roff["combined_score"], "embedding_off": roff["embedding_score"],
                "schema_recall_off": roff["schema_recall"],
                "final_off": roff["final_score"], "detected_off": int(roff["final_score"] >= TAU),
                "detected_combined_off": int(roff["combined_score"] >= TAU),
                "jaccard_on": ron["jaccard_score"], "value_on": ron["value_score"],
                "combined_on": ron["combined_score"], "final_on": ron["final_score"],
                "detected_on": int(ron["final_score"] >= TAU),
                "detected_combined_on": int(ron["combined_score"] >= TAU),
                "method_used_off": roff["method_used"], "method_used_on": ron["method_used"],
            }
            rows.append(row)
            print(f"  [{scenario}] day_{i:02d}  combined_off={row['combined_off']:.4f}  "
                  f"combined_on={row['combined_on']:.4f}  method_on={row['method_used_on']}")

    import pandas as pd
    df = pd.DataFrame(rows)
    df.to_csv(out / "weather_density_sweep_scores.csv", index=False)

    summary_rows = []
    for scenario in DENSITY_SCENARIOS:
        sub = df[df.scenario == scenario]
        summary_rows.append({
            "scenario": scenario, "n_cols_converted": int(sub.n_cols_converted.iloc[0]),
            "density_of_unit_cols": float(sub.density_of_unit_cols.iloc[0]),
            "density_of_schema": float(sub.density_of_schema.iloc[0]),
            "mean_combined_off": float(sub.combined_off.mean()),
            "mean_combined_on": float(sub.combined_on.mean()),
            "mean_final_off": float(sub.final_off.mean()),
            "mean_final_on": float(sub.final_on.mean()),
            "det_combined_off_rate": float(sub.detected_combined_off.mean()),
            "det_combined_on_rate": float(sub.detected_combined_on.mean()),
            "det_on_rate": float(sub.detected_on.mean()),
            "hash_match_rate_on": float((sub.method_used_on == "hash_match").mean()),
        })
    df_summary = pd.DataFrame(summary_rows)
    df_summary.to_csv(out / "weather_density_sweep_summary.csv", index=False)

    write_manifest(
        out,
        params={
            "data_dir": str(args.data_dir), "seed": SEED, "threshold": TAU,
            "weather_days": args.weather_days, "weather_cells": args.weather_cells,
            "n_cols_base": n_cols_base,
            "attack": "value_only_metadata_declared, ALTERATION-DENSITY sweep (all 8 schema "
                      "columns always present; only a FRACTION of the 6 unit-bearing columns "
                      "have their VALUE converted -- names never touched; unit_meta updated "
                      "truthfully for exactly the converted columns). Density parameterised as "
                      "count of unit-bearing columns (1, 3, 6 of 6).",
            "density_scenarios": {k: {"cols": v, "density_of_unit_cols": len(v) / 6,
                                     "density_of_schema": len(v) / 8}
                                 for k, v in DENSITY_SCENARIOS.items()},
            "pairing": "full_base (clone, full 8-col schema with partial value conversion, vs "
                       "the FULL untouched 8-col original of the SAME day/cell sample)",
            "note": "density_6_of_6 is the weather full-clone scenario of table_regen_experiment "
                    "(same attack, same target units).",
        },
        counts={"scoring_rows": len(df), "n_days": len(days), "n_scenarios": len(DENSITY_SCENARIOS)},
        extra={"summary": summary_rows},
    )
    _light_provenance(out, sys.argv)

    print(df_summary.to_string(index=False))
    print(f"elapsed {time.time() - t_start:.1f}s")
    print(f"Saved to {out}/")
    return out


if __name__ == "__main__":
    main()
