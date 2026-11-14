#!/usr/bin/env python3
"""Regeneration of Tables 2 and 3 (full / partial clones) plus negatives and timing."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from inspector.augmentation import DatasetAugmenter
from inspector.loader import Dataset
from inspector.persistence import save_dataset
from inspector.provenance import capture, make_timestamped_output_dir
from inspector import vocab
from inspector.vocab._common import default_data_dir
from inspector.real_datasets import (
    REAL_DATA_SOURCES, _df_to_dataset, _load_semicolon_csv,
    _load_xlsx_flight_data_full, load_weather_days,
)
from inspector.engine import SimilarityPipeline, compute_hash_fingerprint

from partial_clone_experiment import (
    BAGGAGE_NATIVE_ROWS, WEATHER_UNIT_TARGETS, _df_to_dataset_full, _slice_clone,
    baggage_selection, flight_selection, weather_selection,
)

IMPL = Path(__file__).resolve().parent
DATA_DIR = default_data_dir()
TAU = 0.5
SEED = 42
N_CELLS = 5000
N_DAYS = 122
FLIGHT_ROWS = 5000
FLIGHT_CHUNKS = 4
FLIGHT_FILE_ID = REAL_DATA_SOURCES.get("flight_ops", {}).get("filename", "")
WEATHER_FILE_ID = "weather/rasters_2023-08..11"
VARIANTS = ["precautious", "careful", "greedy"]
BAGGAGE_VIEWS = ["arrival", "departure", "transfer", "breakdown"]

WEATHER_A = {"temperature_mean_c": "k", "felt_temperature_mean_c": "k",
             "precipitation_sum_mm": "in", "wind_max_ms": "mph",
             "visibility_max_km": "mi", "sunshine_duration_sum_h": "s"}
FLIGHT_A = {"wingspan_m": "ft"}
FLIGHT_B = {"wingspan_m": "foot"}

ENCODINGS = ["A", "B", "C"]


def make_pipes() -> dict[str, SimilarityPipeline]:
    kw = dict(alpha=0.5, threshold=TAU)
    on = dict(normalize_units=True, normalize_timezones=True)
    return {
        "off": SimilarityPipeline(**kw),
        "on": SimilarityPipeline(**kw, **on),
        "vao_off": SimilarityPipeline(**kw, value_aware_only=True),
        "vao_on": SimilarityPipeline(**kw, **on, value_aware_only=True),
    }


METRICS = ["jaccard", "value", "combined", "embedding", "schema_recall", "gated", "final"]
NAN = float("nan")


def score_pair(a: Dataset, b: Dataset, pipes: dict, full: bool = True) -> dict:
    """All metrics for one pair, defence off and on."""
    row: dict = {}
    for d in ("off", "on"):
        if full:
            rep = pipes[d].compare(a, b)
            row.update({
                f"jaccard_{d}": rep.jaccard_score, f"value_{d}": rep.value_score,
                f"combined_{d}": rep.combined_score, f"embedding_{d}": rep.embedding_score,
                f"schema_recall_{d}": rep.schema_recall, f"gated_{d}": rep.gated_reuse,
                f"final_{d}": rep.final_score, f"method_{d}": rep.method_used,
                f"t_total_{d}": rep.stage_timings.get("total_s", NAN),
                f"t_units_{d}": rep.stage_timings.get("units_s", NAN),
                f"t_tz_{d}": rep.stage_timings.get("tz_s", NAN),
                f"t_hash_{d}": rep.stage_timings.get("hash_s", NAN),
            })
        else:
            for m in METRICS:
                row[f"{m}_{d}"] = NAN
            row[f"method_{d}"] = ""
            for t in ("total", "units", "tz", "hash"):
                row[f"t_{t}_{d}"] = NAN
        v = pipes[f"vao_{d}"].compare(a, b)
        row[f"vao_{d}"] = v.final_score
        row[f"vao_method_{d}"] = v.method_used
    row["has_full_pipeline"] = int(full)
    return row


def warm(pipes):
    w = load_weather_days(DATA_DIR / REAL_DATA_SOURCES["weather"]["dirname"],
                          n_days=1, n_cells=200, seed=SEED)
    c = DatasetAugmenter(SEED).convert_units_and_epoch_value_only(w[0], unit_targets=WEATHER_UNIT_TARGETS)
    for k in ("off", "on"):
        pipes[k].compare(w[0], c)


def load_weather() -> list[Dataset]:
    ds = load_weather_days(DATA_DIR / REAL_DATA_SOURCES["weather"]["dirname"],
                           n_days=N_DAYS, n_cells=N_CELLS, seed=SEED, all_days=True)
    assert len(ds) == N_DAYS, len(ds)
    return ds


def load_flight() -> tuple[list[Dataset], dict]:
    fp = DATA_DIR / REAL_DATA_SOURCES["flight_ops"]["filename"]
    df, meta = _load_xlsx_flight_data_full(fp, sample_n=FLIGHT_ROWS * FLIGHT_CHUNKS,
                                           seed=SEED, keep_all_columns=True)
    chunks = [_df_to_dataset_full(df.iloc[i * FLIGHT_ROWS:(i + 1) * FLIGHT_ROWS].reset_index(drop=True),
                                  name=f"real/flight_chunk{i}")
              for i in range(FLIGHT_CHUNKS)]
    return chunks, meta


def load_baggage() -> dict[str, Dataset]:
    out = {}
    for view in BAGGAGE_VIEWS:
        key = f"{view}_baggage"
        df = _load_semicolon_csv(DATA_DIR / REAL_DATA_SOURCES[key]["filename"],
                                 sample_n=BAGGAGE_NATIVE_ROWS[key] + 1, seed=SEED)
        out[view] = _df_to_dataset(df, name=f"real/{key}")
    return out


def a_rename(targets: dict[str, str]) -> dict[str, str]:
    from inspector.units import split_suffix
    return {f: f"{split_suffix(f)[0]}_{t}" for f, t in targets.items()}


def make_full_clone(base: Dataset, source: str, enc: str) -> Dataset:
    aug = DatasetAugmenter(seed=SEED)
    if source == "weather":
        a_t, b_t = WEATHER_A, WEATHER_UNIT_TARGETS
    elif source == "flight":
        a_t, b_t = FLIGHT_A, FLIGHT_B
    else:
        a_t, b_t = {}, {}
    if enc == "A":
        c = aug.convert_units_and_epoch_named_targets(base, a_t)
    else:
        c = aug.convert_units_and_epoch_value_only(base, unit_targets=b_t)
        if enc == "C":
            c.unit_meta = {}
    return c


def partial_cols(sel: dict, variant: str, source: str, enc: str) -> list[str]:
    cols = sel[variant]["cols"]
    if enc == "A":
        ren = a_rename(WEATHER_A if source == "weather" else FLIGHT_A if source == "flight" else {})
        cols = [ren.get(c, c) for c in cols]
    return cols


def make_partial(clone: Dataset, sel: dict, variant: str, source: str, enc: str) -> Dataset:
    return _slice_clone(clone, partial_cols(sel, variant, source, enc), f".{variant}")


def n_attacked(base: Dataset) -> int:
    from inspector.timezones import count_timezone_bearing_fields
    from inspector.units import count_unit_bearing_fields
    return count_unit_bearing_fields(base) + count_timezone_bearing_fields(base)


def n_cols(ds: Dataset) -> int:
    return len(ds.data[0]) if isinstance(ds.data, list) and ds.data and isinstance(ds.data[0], dict) else 0


class CsvOut:
    def __init__(self, path: Path):
        self.path = path
        self.f = None
        self.w = None

    def write(self, row: dict):
        if self.w is None:
            self.f = open(self.path, "w", newline="")
            self.w = csv.DictWriter(self.f, fieldnames=list(row))
            self.w.writeheader()
        self.w.writerow(row)
        self.f.flush()

    def close(self):
        if self.f:
            self.f.close()


def pos_row(*, enc, kind, source, view, sample_id, source_file_id, variant, base, clone,
            U, T, F, n_att, pipes, sc=None):
    sc = sc if sc is not None else score_pair(base, clone, pipes)
    row = {
        "encoding": enc, "kind": kind, "source": source, "view": view, "sample_id": sample_id,
        "source_file_id": source_file_id, "variant": variant,
        "n_rows_base": len(base.data), "n_rows_clone": len(clone.data),
        "n_cols_base": n_cols(base), "n_cols_clone": n_cols(clone),
        "F": F, "U": U, "T": T, "n_cols_attacked": n_att,
        "base_sha": compute_hash_fingerprint(base)[:16], "clone_sha": compute_hash_fingerprint(clone)[:16],
        "unit_meta_declared": len(getattr(clone, "unit_meta", {}) or {}),
    }
    row.update(sc)
    for m in ("final", "combined"):
        for d in ("off", "on"):
            row[f"detected_{m}_{d}"] = int(row[f"{m}_{d}"] >= TAU) if row[f"{m}_{d}"] == row[f"{m}_{d}"] else ""
    for d in ("off", "on"):
        row[f"detected_vao_{d}"] = int(row[f"vao_{d}"] >= TAU)
    return row


def phase_init(args):
    out = make_timestamped_output_dir(IMPL / "experiments" / "table_regen")
    out.mkdir(parents=True, exist_ok=True)
    (out / "datasets").mkdir()
    capture(out, args={"cmd": "init"}, argv=sys.argv, implementation_root=IMPL)
    diff = subprocess.run(["git", "diff", "HEAD"], capture_output=True, text=True, cwd=IMPL.parent).stdout
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=IMPL.parent).stdout.strip()
    (out / "provenance" / "git_head_and_diff_hash.json").write_text(json.dumps({
        "head": head, "diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
        "diff_bytes": len(diff)}, indent=2))
    manifest = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "params": {"tau": TAU, "seed": SEED, "weather_days": N_DAYS, "weather_cells": N_CELLS,
                   "flight_rows_per_chunk": FLIGHT_ROWS, "flight_chunks": FLIGHT_CHUNKS,
                   "flight_source_file": FLIGHT_FILE_ID, "baggage_rows": "native",
                   "encodings": {"A": "name-encoded (paper targets, suffix renamed, no unit_meta)",
                                 "B": "value-only, metadata-declared unit_meta",
                                 "C": "value-only, metadata withheld (names unchanged, no unit_meta)"}},
        "git_head": head, "git_diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
        "dataset_persistence": ("datasets/ holds the exact base/clone/partial datasets for weather "
                                 "days 0, 60, 121, flight chunk 0 and baggage (base, shared clone, greedy "
                                 "partial). All others are reproducible from seed and are identified by "
                                 "base_sha/clone_sha (first 16 hex of the pipeline's own SHA-256) in the CSVs."),
        "phases_done": {},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(out)


def mark_done(run: Path, phase: str, info: dict):
    (run / f"phase_done_{phase}.json").write_text(json.dumps(
        {"finished": time.strftime("%Y-%m-%dT%H:%M:%S"), **info}, indent=2, default=str))


def phase_positives(args):
    run = Path(args.run_dir)
    enc = args.encoding
    pipes = make_pipes()
    warm(pipes)
    out = CsvOut(run / f"positives_{enc}.csv")
    t0 = time.time()
    wsel = weather_selection()
    weather = load_weather()
    print(f"[{enc}] weather loaded {len(weather)} days", flush=True)
    for i, base in enumerate(weather):
        date = base.data[0]["obs_date"]
        clone = make_full_clone(base, "weather", enc)
        common = dict(enc=enc, source="weather", view="", sample_id=f"day_{i:03d}_{date}",
                      source_file_id=WEATHER_FILE_ID, base=base, pipes=pipes, F=n_cols(base))
        out.write(pos_row(kind="full", variant="full", clone=clone, U=6, T=n_cols(clone),
                          n_att=n_attacked(base), **common))
        if i in (0, 60, 121):
            for ds in (base, clone):
                save_dataset(ds, run / "datasets", name=f"weather_d{i:03d}_{enc}_{ds.source_path}")
        for v in VARIANTS:
            part = make_partial(clone, wsel, v, "weather", enc)
            out.write(pos_row(kind="partial", variant=v, clone=part, U=wsel[v]["n_unit"],
                              T=len(wsel[v]["cols"]), n_att=n_attacked(base), **common))
            if i == 0:
                save_dataset(part, run / "datasets", name=f"weather_d000_{enc}_{v}")
        if i % 10 == 0:
            print(f"[{enc}] weather day {i}  {time.time()-t0:.0f}s", flush=True)
    del weather

    fsel = flight_selection(DATA_DIR)
    chunks, fmeta = load_flight()
    for i in range(3):
        base = chunks[i]
        clone = make_full_clone(base, "flight", enc)
        common = dict(enc=enc, source="flight", view="", sample_id=f"chunk_{i}",
                      source_file_id=f"{FLIGHT_FILE_ID}#rows[{i*FLIGHT_ROWS}:{(i+1)*FLIGHT_ROWS}] of {FLIGHT_ROWS*FLIGHT_CHUNKS}-row seeded sample (total_rows={fmeta['total_rows']})",
                      base=base, pipes=pipes, F=n_cols(base))
        out.write(pos_row(kind="full", variant="full", clone=clone, U=42, T=n_cols(clone),
                          n_att=n_attacked(base), **common))
        if i == 0:
            for ds in (base, clone):
                save_dataset(ds, run / "datasets", name=f"flight_c0_{enc}_{ds.source_path}")
        for v in VARIANTS:
            part = make_partial(clone, fsel, v, "flight", enc)
            out.write(pos_row(kind="partial", variant=v, clone=part, U=fsel[v]["n_unit"],
                              T=len(fsel[v]["cols"]), n_att=n_attacked(base), **common))
        print(f"[{enc}] flight chunk {i} done {time.time()-t0:.0f}s", flush=True)
    out.close()
    mark_done(run, f"positives_{enc}", {"seconds": time.time() - t0})


def phase_baggage(args):
    run = Path(args.run_dir)
    pipes = make_pipes()
    warm(pipes)
    out = CsvOut(run / "positives_baggage.csv")
    bsel = baggage_selection(DATA_DIR)
    bags = load_baggage()
    t0 = time.time()
    for view, base in bags.items():
        clones = {e: make_full_clone(base, "baggage", e) for e in ENCODINGS}
        assert clones["A"].data == clones["B"].data == clones["C"].data, "baggage clones differ across encodings"
        clone = clones["B"]
        sel = bsel[f"{view}_baggage"]
        scored = []
        scored.append(("full", "full", clone, sel["n_ts"], len(clone.data[0])))
        for v in VARIANTS:
            part = make_partial(clone, sel, v, "baggage", "B")
            scored.append(("partial", v, part, sel[v]["n_unit"], len(sel[v]["cols"])))
        for kind, v, c, U, T in scored:
            sc = score_pair(base, c, pipes)
            for enc in ENCODINGS:
                row = pos_row(enc=enc, kind=kind, source="baggage", view=view, sample_id="native",
                              source_file_id=REAL_DATA_SOURCES[f"{view}_baggage"]["filename"],
                              variant=v, base=base, clone=c, U=U, T=T, F=n_cols(base),
                              n_att=n_attacked(base), pipes=pipes, sc=sc)
                row["scores_shared_across_encodings"] = 1
                out.write(row)
            if v in ("full", "greedy"):
                save_dataset(c, run / "datasets", name=f"baggage_{view}_clone_{v}")
        save_dataset(base, run / "datasets", name=f"baggage_{view}_base")
        print(f"baggage {view} done {time.time()-t0:.0f}s", flush=True)
    out.close()
    mark_done(run, "baggage", {"seconds": time.time() - t0})


def phase_negatives(args):
    run = Path(args.run_dir)
    group = args.group
    pipes = make_pipes()
    warm(pipes)
    out = CsvOut(run / f"negatives_{group}.csv")
    t0 = time.time()
    rng = np.random.default_rng(7)

    def emit(neg_type, enc, source, a_id, b_id, rank, a, b, full, extra=None):
        sc = score_pair(a, b, pipes, full=full)
        row = {"neg_type": neg_type, "encoding": enc, "source": source, "left_id": a_id,
               "right_id": b_id, "partner_rank": rank, "n_rows_left": len(a.data),
               "n_rows_right": len(b.data), "n_cols_left": n_cols(a), "n_cols_right": n_cols(b),
               "left_sha": compute_hash_fingerprint(a)[:16], "right_sha": compute_hash_fingerprint(b)[:16]}
        row.update(extra or {})
        row.update(sc)
        for d in ("off", "on"):
            row[f"detected_vao_{d}"] = int(row[f"vao_{d}"] >= TAU)
            if full:
                row[f"detected_final_{d}"] = int(row[f"final_{d}"] >= TAU)
        out.write(row)

    if group in ("weather_base", "weather_clones", "weather_partials", "weather_partials_AC"):
        weather = load_weather()
        wsel = weather_selection()
        partners = {i: [int(j) for j in rng.choice([k for k in range(N_DAYS) if k != i], size=10, replace=False)]
                    for i in range(N_DAYS)}
        specs = {
            "weather_base": [("base_vs_other_base", None, 1)],
            "weather_clones": [("fullclone_vs_other_base", "B", 1), ("fullclone_vs_other_base", "A", 3),
                               ("fullclone_vs_other_base", "C", 3)],
            "weather_partials": [(f"partial_{v}_vs_other_base", "B", 3) for v in VARIANTS],
            "weather_partials_AC": [(f"partial_{v}_vs_other_base", e, 3) for e in ("A", "C") for v in VARIANTS],
        }[group]
        for neg_type, enc, stride in specs:
            for i in range(0, N_DAYS, stride):
                base = weather[i]
                if enc is None:
                    left = base
                else:
                    clone = make_full_clone(base, "weather", enc)
                    left = clone
                    if neg_type.startswith("partial_"):
                        left = make_partial(clone, wsel, neg_type.split("_")[1], "weather", enc)
                for rank, j in enumerate(partners[i]):
                    emit(neg_type, enc or "none", "weather", f"d{i:03d}", f"d{j:03d}", rank,
                         left, weather[j], full=(rank < args.full_partners))
            print(f"{neg_type}/{enc} done {time.time()-t0:.0f}s", flush=True)

    elif group == "misc":
        chunks, _ = load_flight()
        fsel = flight_selection(DATA_DIR)
        for i, j in [(0, 1), (0, 2), (1, 2), (0, 3)]:
            emit("flight_base_vs_disjoint_base", "none", "flight", f"c{i}", f"c{j}", 0,
                 chunks[i], chunks[j], True)
        for enc in ("B", "C", "A"):
            cl = make_full_clone(chunks[0], "flight", enc)
            for rank, j in enumerate((1, 2)):
                emit("flight_fullclone_vs_disjoint_base", enc, "flight", "c0", f"c{j}", rank, cl, chunks[j], True)
        cl = make_full_clone(chunks[0], "flight", "B")
        emit("flight_partial_greedy_vs_disjoint_base", "B", "flight", "c0", "c1", 0,
             make_partial(cl, fsel, "greedy", "flight", "B"), chunks[1], True)
        print(f"flight negatives done {time.time()-t0:.0f}s", flush=True)
        bsel = baggage_selection(DATA_DIR)
        bags = load_baggage()

        def half(ds, which):
            h = len(ds.data) // 2
            d = ds.data[:h] if which == 0 else ds.data[h:]
            return Dataset(data=d, modality=ds.modality, source_path=f"{ds.source_path}.half{which}")
        for view, base in bags.items():
            cl = make_full_clone(base, "baggage", "B")
            part = make_partial(cl, bsel[f"{view}_baggage"], "greedy", "baggage", "B")
            emit("baggage_half0_vs_half1", "none", f"baggage_{view}", "h0", "h1", 0, half(base, 0), half(base, 1), True)
            emit("baggage_clonehalf0_vs_basehalf1", "B", f"baggage_{view}", "h0", "h1", 0, half(cl, 0), half(base, 1), True)
            emit("baggage_partial_greedy_half0_vs_basehalf1", "B", f"baggage_{view}", "h0", "h1", 0, half(part, 0), half(base, 1), True)
            print(f"baggage halves {view} {time.time()-t0:.0f}s", flush=True)
        views = list(bags)
        for a in views:
            for b in views:
                if a == b:
                    continue
                cl = make_full_clone(bags[a], "baggage", "B")
                if views.index(a) < views.index(b):
                    emit("baggage_crossview_base_vs_base", "none", "baggage", a, b, 0, bags[a], bags[b], True)
                emit("baggage_crossview_clone_vs_base", "B", "baggage", a, b, 0, cl, bags[b], True)
            print(f"baggage cross {a} {time.time()-t0:.0f}s", flush=True)
        weather = load_weather()
        w0 = weather[0]
        wc = make_full_clone(w0, "weather", "B")
        f0 = chunks[0]
        fc = make_full_clone(f0, "flight", "B")
        emit("crosssource_weather_vs_flight", "none", "x", "w0", "f0", 0, w0, f0, True)
        emit("crosssource_weatherclone_vs_flight", "B", "x", "w0", "f0", 0, wc, f0, True)
        emit("crosssource_weather_vs_baggage_arrival", "none", "x", "w0", "arrival", 0, w0, bags["arrival"], True)
        emit("crosssource_flight_vs_baggage_arrival", "none", "x", "f0", "arrival", 0, f0, bags["arrival"], True)
        emit("crosssource_flightclone_vs_baggage_arrival", "B", "x", "f0", "arrival", 0, fc, bags["arrival"], True)
    out.close()
    mark_done(run, f"negatives_{group}", {"seconds": time.time() - t0})


def phase_consistency(args):
    """Summary checks on the weather full clones and a day-0/day-1 probe."""
    import pandas as pd
    run = Path(args.run_dir)
    res: dict = {}
    pb = pd.read_csv(run / "positives_B.csv")
    wf = pb[(pb.source == "weather") & (pb.kind == "full")]
    res["weather_B_full_n"] = len(wf)
    res["weather_B_mean_combined_off"] = float(wf.combined_off.mean())
    res["weather_B_combined_on_all_1"] = bool((wf.combined_on == 1.0).all())
    res["weather_B_hash_match_on_count"] = int((wf.method_on == "hash_match").sum())
    res["vao_equals_combined_weather_B_max_abs_diff"] = float(
        np.abs(wf.vao_off.to_numpy() - wf.combined_off.to_numpy()).max())
    pipes = make_pipes()
    weather = load_weather()
    r = pipes["off"].compare(weather[0], weather[1])
    res["probe_d0_vs_d1_final_off"] = r.final_score
    res["probe_d0_vs_d1_combined_off"] = r.combined_score
    (run / "consistency.json").write_text(json.dumps(res, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    print(json.dumps(res, indent=2, default=str))


def phase_timing(args):
    run = Path(args.run_dir)
    reps = args.reps
    pipes = make_pipes()
    warm(pipes)
    out = CsvOut(run / "timing.csv")
    weather = load_weather()
    wsel = weather_selection()
    chunks, _ = load_flight()
    fsel = flight_selection(DATA_DIR)
    bags = load_baggage()
    bsel = baggage_selection(DATA_DIR)
    cases = []
    for i in (0, 40, 80, 121):
        b = weather[i]
        cl = make_full_clone(b, "weather", "B")
        cases += [(f"weather_d{i}", "fullclone_B", b, cl),
                  (f"weather_d{i}", "partial_greedy_B", b, make_partial(cl, wsel, "greedy", "weather", "B")),
                  (f"weather_d{i}", "other_day_negative", b, weather[(i + 17) % N_DAYS])]
    b = chunks[0]
    cl = make_full_clone(b, "flight", "B")
    cases += [("flight_c0", "fullclone_B", b, cl),
              ("flight_c0", "partial_greedy_B", b, make_partial(cl, fsel, "greedy", "flight", "B")),
              ("flight_c0", "disjoint_negative", b, chunks[1])]
    b = bags["arrival"]
    cl = make_full_clone(b, "baggage", "B")
    cases += [("baggage_arrival", "fullclone", b, cl),
              ("baggage_arrival", "partial_greedy", b, make_partial(cl, bsel["arrival_baggage"], "greedy", "baggage", "B"))]
    for src, kind, a, c in cases:
        for rep in range(reps):
            row = {"source": src, "case": kind, "rep": rep, "n_rows": len(a.data),
                   "n_cols_base": n_cols(a), "n_cols_clone": n_cols(c)}
            for d in ("off", "on"):
                rep_ = pipes[d].compare(a, c)
                st = rep_.stage_timings
                row.update({f"method_{d}": rep_.method_used, f"total_{d}_s": st.get("total_s", NAN),
                            f"units_{d}_s": st.get("units_s", NAN), f"tz_{d}_s": st.get("tz_s", NAN),
                            f"hash_{d}_s": st.get("hash_s", NAN), f"final_{d}": rep_.final_score})
            out.write(row)
        print(src, kind, "done", flush=True)
    out.close()
    mark_done(run, "timing", {"reps": reps})


def phase_retrieval(args):
    """Phase 2: 1-vs-all retrieval."""
    from inspector.units import normalize_dataset
    from inspector.timezones import normalize_timezones_dataset
    run = Path(args.run_dir)
    enc = args.encoding
    cells = args.cells
    pipes = make_pipes()
    warm(pipes)
    days = load_weather_days(DATA_DIR / REAL_DATA_SOURCES["weather"]["dirname"],
                             n_days=N_DAYS, n_cells=cells, seed=SEED, all_days=True)
    refs = days
    refs_n = [normalize_timezones_dataset(normalize_dataset(d)) for d in refs]
    out = CsvOut(run / f"retrieval_{enc}_{cells}cells{args.suffix}.csv")
    idxs = list(range(args.start, N_DAYS, args.stride))
    t0 = time.time()
    for i in idxs:
        clone = make_full_clone(refs[i], "weather", enc)
        clone_n = normalize_timezones_dataset(normalize_dataset(clone))
        for j in range(N_DAYS):
            row = {"encoding": enc, "cells": cells, "clone_day": i, "ref_day": j, "is_true": int(i == j)}
            roff = pipes["off"].compare(refs[j], clone)
            ron = pipes["off"].compare(refs_n[j], clone_n)
            vo = pipes["vao_off"].compare(refs[j], clone)
            row.update({"combined_off": roff.combined_score, "final_off": roff.final_score,
                        "combined_on": ron.combined_score, "final_on": ron.final_score,
                        "method_on": ron.method_used, "vao_off": vo.final_score})
            row["verify_final_on_diff"] = NAN
            row["verify_combined_on_diff"] = NAN
            if args.verify and j in (i, (i + 1) % N_DAYS):
                rv = pipes["on"].compare(refs[j], clone)
                row["verify_final_on_diff"] = abs(rv.final_score - ron.final_score)
                row["verify_combined_on_diff"] = abs(rv.combined_score - ron.combined_score)
            out.write(row)
        print(f"clone {i} done {time.time()-t0:.0f}s", flush=True)
    out.close()
    mark_done(run, f"retrieval_{enc}_{cells}{args.suffix}", {"seconds": time.time() - t0})


def main():
    vocab.announce()
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    for name in ("positives", "baggage", "negatives", "consistency", "timing", "retrieval"):
        p = sub.add_parser(name)
        p.add_argument("--run-dir", required=True)
        if name == "positives":
            p.add_argument("--encoding", choices=ENCODINGS, required=True)
        if name == "negatives":
            p.add_argument("--group", required=True, choices=["weather_base", "weather_clones", "weather_partials", "weather_partials_AC", "misc"])
            p.add_argument("--full-partners", type=int, default=2)
        if name == "timing":
            p.add_argument("--reps", type=int, default=5)
        if name == "retrieval":
            p.add_argument("--encoding", choices=ENCODINGS, default="B")
            p.add_argument("--cells", type=int, default=500)
            p.add_argument("--stride", type=int, default=1)
            p.add_argument("--verify", action="store_true")
            p.add_argument("--start", type=int, default=0)
            p.add_argument("--suffix", default="")
    args = ap.parse_args()
    {"init": phase_init, "positives": phase_positives, "baggage": phase_baggage,
     "negatives": phase_negatives, "consistency": phase_consistency,
     "timing": phase_timing, "retrieval": phase_retrieval}[args.cmd](args)


if __name__ == "__main__":
    main()
