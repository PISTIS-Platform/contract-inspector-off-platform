#!/usr/bin/env python3
"""Follow-up experiments on the table_regen parent run: adjacent days, row order, identifier ablation, like-for-like negatives."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import subprocess
import time
from pathlib import Path


import table_regen_experiment as T
from inspector import vocab
from inspector.loader import Dataset
from inspector.engine import compute_hash_fingerprint
from partial_clone_experiment import baggage_selection, flight_selection, weather_selection

IMPL = Path(__file__).resolve().parent
ID_KEYS = ("cell_id", "obs_date")
VARIANTS = T.VARIANTS


def with_rows(ds: Dataset, rows: list, tag: str = "") -> Dataset:
    d = copy.copy(ds)
    d.data = list(rows)
    d.source_path = ds.source_path + tag
    d.filename = Path(d.source_path).name
    return d


def drop_ids(ds: Dataset) -> Dataset:
    return with_rows(ds, [{k: v for k, v in r.items() if k not in ID_KEYS} for r in ds.data])


def project(ds: Dataset, cols: list[str]) -> Dataset:
    keep = set(cols)
    return Dataset(data=[{k: v for k, v in r.items() if k in keep} for r in ds.data],
                   modality=ds.modality, source_path=ds.source_path + ".proj")


def row_transforms(ds: Dataset) -> dict[str, Dataset]:
    rows = ds.data
    n = len(rows)
    shuf = list(rows)
    random.Random(T.SEED).shuffle(shuf)
    rng = random.Random(T.SEED)
    rand50 = [r for r in rows if rng.random() < 0.5]
    return {"permuted": with_rows(ds, shuf, ".perm"),
            "every2nd": with_rows(ds, rows[::2], ".every2nd"),
            "random50_ordered": with_rows(ds, rand50, ".rand50"),
            "prefix50": with_rows(ds, rows[: n // 2], ".prefix50")}


def clone_kinds(base: Dataset, source: str, enc: str, sel: dict) -> dict[str, Dataset]:
    cl = T.make_full_clone(base, source, enc)
    out = {"full": cl}
    for v in VARIANTS:
        out[v] = T.make_partial(cl, sel, v, source, enc)
    return out


def phase_init(args):
    parent = Path(args.parent).resolve()
    out = parent.parent / f"run_{time.strftime('%Y-%m-%d_%H%M%S')}_followup"
    out.mkdir(parents=True)
    (out / "datasets").mkdir()
    (out / "provenance").mkdir()
    gitroot = IMPL.parent
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=gitroot).stdout.strip()
    diff = subprocess.run(["git", "diff", "HEAD"], capture_output=True, text=True, cwd=gitroot).stdout
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).exists() else None
    pm = json.loads((parent / "manifest.json").read_text())
    (out / "manifest.json").write_text(json.dumps({
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "parent_run": (str(parent.relative_to(IMPL)) if IMPL in parent.parents else parent.name), "parent_params": pm["params"],
        "parent_git_head": pm["git_head"], "parent_git_diff_sha256": pm["git_diff_sha256"],
        "git_head": head, "git_diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
        "harness": "implementation/table_followup_experiment.py",
        "harness_sha256": sha(__file__),
        "parent_harness_sha256": sha(IMPL / "table_regen_experiment.py"),
        "partial_clone_experiment_sha256": sha(IMPL / "partial_clone_experiment.py"),
        "inspector_similarity_sha256": sha(IMPL / "inspector" / "similarity.py"),
        "row_transform_seed": T.SEED,
        "tasks": {"1": "weather_reference_adjacent.csv", "2": "row_order_limits.csv",
                  "3": "identifier_ablation_both.csv", "4": "calibration_split.csv",
                  "5": "negatives_partial_like4like.csv"},
        "notes": ("clone-vs-adjacent partials are scored with the deployed pipeline (full) only for "
                  "days i%3==0, vao-only otherwise; base-vs-base adjacent pairs are all full. "
                  "Datasets are reproducible from seed 42 via the harness; row-order and id-dropped "
                  "variants are derived deterministically (see row_transforms/drop_ids)."),
    }, indent=2))
    print(out)


def emit_factory(run: Path, name: str, pipes):
    out = T.CsvOut(run / name)

    def emit(full: bool, a: Dataset, b: Dataset, **meta):
        sc = T.score_pair(a, b, pipes, full=full)
        row = {**meta, "n_rows_left": len(a.data), "n_rows_right": len(b.data),
               "n_cols_left": T.n_cols(a), "n_cols_right": T.n_cols(b)}
        row.update(sc)
        out.write(row)
    return out, emit


def phase_adjacent(args):
    run = Path(args.run_dir)
    pipes = T.make_pipes()
    T.warm(pipes)
    out, emit = emit_factory(run, f"weather_reference_adjacent.shard{args.shard}.csv", pipes)
    W = T.load_weather()
    wsel = weather_selection()
    t0 = time.time()
    for i in range(T.N_DAYS):
        if i % args.nshards != args.shard:
            continue
        if i + 1 < T.N_DAYS:
            emit(True, W[i], W[i + 1], pair_type="base_adjacent", encoding="none", kind="base",
                 variant="", left_day=i, right_day=i + 1, gap=1)
        for enc in ("A", "B"):
            kinds = clone_kinds(W[i], "weather", enc, wsel)
            for kind, c in kinds.items():
                for j in (i - 1, i + 1):
                    if 0 <= j < T.N_DAYS:
                        emit(i % 3 == 0, c, W[j], pair_type="clone_vs_adjacent_base", encoding=enc,
                             kind="full" if kind == "full" else "partial", variant=kind,
                             left_day=i, right_day=j, gap=abs(i - j))
        print(f"shard{args.shard} day {i} {time.time()-t0:.0f}s", flush=True)
    out.close()
    T.mark_done(run, f"adjacent_shard{args.shard}", {"seconds": time.time() - t0})


def phase_roworder(args):
    run = Path(args.run_dir)
    pipes = T.make_pipes()
    T.warm(pipes)
    tag = args.source if args.chunk is None else f"{args.source}{args.chunk}"
    out, emit = emit_factory(run, f"row_order_limits.{tag}.csv", pipes)
    t0 = time.time()
    if args.source == "weather":
        W = T.load_weather()
        for i in (0, 60, 121):
            for enc in ("A", "B"):
                cl = T.make_full_clone(W[i], "weather", enc)
                for tname, d in row_transforms(cl).items():
                    emit(True, W[i], d, source="weather", sample_id=f"day_{i:03d}", encoding=enc,
                         transform=tname, base_sha=compute_hash_fingerprint(W[i])[:16],
                         clone_sha=compute_hash_fingerprint(d)[:16])
                print(f"weather d{i} {enc} {time.time()-t0:.0f}s", flush=True)
    elif args.source == "flight":
        chunks, _ = T.load_flight()
        for i in ([args.chunk] if args.chunk is not None else range(3)):
            for enc in ("A", "B"):
                cl = T.make_full_clone(chunks[i], "flight", enc)
                for tname, d in row_transforms(cl).items():
                    emit(True, chunks[i], d, source="flight", sample_id=f"chunk_{i}", encoding=enc,
                         transform=tname, base_sha=compute_hash_fingerprint(chunks[i])[:16],
                         clone_sha=compute_hash_fingerprint(d)[:16])
                    print(f"flight c{i} {enc} {tname} {time.time()-t0:.0f}s", flush=True)
    else:
        bags = T.load_baggage()
        for view, base in bags.items():
            cl = T.make_full_clone(base, "baggage", "B")
            for tname, d in row_transforms(cl).items():
                emit(True, base, d, source="baggage", sample_id=view, encoding="B(=A=C)",
                     transform=tname, base_sha=compute_hash_fingerprint(base)[:16],
                     clone_sha=compute_hash_fingerprint(d)[:16])
            print(f"baggage {view} {time.time()-t0:.0f}s", flush=True)
    out.close()
    T.mark_done(run, f"roworder_{tag}", {"seconds": time.time() - t0})


def phase_idablation(args):
    """Drop cell_id + obs_date from BOTH sides; vao off/on only."""
    run = Path(args.run_dir)
    pipes = T.make_pipes()
    T.warm(pipes)
    out, emit = emit_factory(run, f"identifier_ablation_both.shard{args.shard}.csv", pipes)
    W = T.load_weather()
    Wd = [drop_ids(d) for d in W]
    wsel = weather_selection()
    t0 = time.time()
    for i in range(T.N_DAYS):
        if i % args.nshards != args.shard:
            continue
        if i + 1 < T.N_DAYS:
            emit(False, Wd[i], Wd[i + 1], pair_type="base_adjacent_ids_dropped", encoding="none",
                 kind="base", variant="", left_day=i, right_day=i + 1,
                 n_cols_after_drop=T.n_cols(Wd[i]))
        for enc in ("A", "B"):
            for kind, c in clone_kinds(W[i], "weather", enc, wsel).items():
                cd = drop_ids(c)
                emit(False, Wd[i], cd, pair_type="clone_vs_own_base_ids_dropped", encoding=enc,
                     kind="full" if kind == "full" else "partial", variant=kind, left_day=i, right_day=i,
                     n_cols_after_drop=T.n_cols(cd))
                if enc == "A":
                    for j in (i - 1, i + 1):
                        if 0 <= j < T.N_DAYS:
                            emit(False, Wd[j], cd, pair_type="clone_vs_adjacent_base_ids_dropped",
                                 encoding=enc, kind="full" if kind == "full" else "partial",
                                 variant=kind, left_day=i, right_day=j, n_cols_after_drop=T.n_cols(cd))
        print(f"shard{args.shard} day {i} {time.time()-t0:.0f}s", flush=True)
    out.close()
    T.mark_done(run, f"idablation_shard{args.shard}", {"seconds": time.time() - t0})


def phase_negatives(args):
    run = Path(args.run_dir)
    pipes = T.make_pipes()
    T.warm(pipes)
    tag = args.source if args.chunk is None else f"{args.source}{args.chunk}"
    out, emit = emit_factory(run, f"negatives_partial_like4like.{tag}.csv", pipes)
    t0 = time.time()
    if args.source == "flight":
        fsel = flight_selection(T.DATA_DIR)
        chunks, _ = T.load_flight()
        i = args.chunk
        for enc in ("A", "B"):
            cl = T.make_full_clone(chunks[i], "flight", enc)
            for v in VARIANTS:
                part = T.make_partial(cl, fsel, v, "flight", enc)
                orig_cols = fsel[v]["cols"]
                for j in range(T.FLIGHT_CHUNKS):
                    if j == i:
                        continue
                    other = project(chunks[j], orig_cols)
                    emit(True, part, other, source="flight", neg_type="partial_vs_same_variant_projection_other_chunk",
                         encoding=enc, variant=v, left_id=f"chunk_{i}", right_id=f"chunk_{j}",
                         T_cols=len(orig_cols), n_cols_projected=T.n_cols(other))
                    print(f"flight c{i} {enc} {v} vs c{j} {time.time()-t0:.0f}s", flush=True)
    else:
        bsel = baggage_selection(T.DATA_DIR)
        bags = T.load_baggage()
        for view, base in bags.items():
            cl = T.make_full_clone(base, "baggage", "B")
            h = len(base.data) // 2
            for v in VARIANTS:
                cols = bsel[f"{view}_baggage"][v]["cols"]
                part = T.make_partial(cl, bsel[f"{view}_baggage"], v, "baggage", "B")
                for which in (0, 1):
                    pr = with_rows(part, part.data[:h] if which == 0 else part.data[h:])
                    oth = project(with_rows(base, base.data[h:] if which == 0 else base.data[:h]), cols)
                    emit(True, pr, oth, source=f"baggage_{view}",
                         neg_type="partial_half_vs_same_variant_projection_other_half", encoding="B(=A=C)",
                         variant=v, left_id=f"clone_half{which}", right_id=f"base_half{1-which}",
                         T_cols=len(cols), n_cols_projected=T.n_cols(oth))
            print(f"baggage {view} {time.time()-t0:.0f}s", flush=True)
    out.close()
    T.mark_done(run, f"negatives_{tag}", {"seconds": time.time() - t0})


def phase_consistency(args):
    """Recompute parent row: weather d0 full clone enc B, compare to parent CSV."""
    import pandas as pd
    run = Path(args.run_dir)
    parent = IMPL / json.loads((run / "manifest.json").read_text())["parent_run"]
    pipes = T.make_pipes()
    T.warm(pipes)
    from inspector.real_datasets import REAL_DATA_SOURCES, load_weather_days
    days = load_weather_days(T.DATA_DIR / REAL_DATA_SOURCES["weather"]["dirname"], n_days=T.N_DAYS,
                             n_cells=T.N_CELLS, seed=T.SEED, all_days=True)
    cl = T.make_full_clone(days[0], "weather", "B")
    sc = T.score_pair(days[0], cl, pipes)
    pb = pd.read_csv(parent / "positives_B.csv")
    row = pb[(pb.source == "weather") & (pb.kind == "full") & (pb.sample_id.str.startswith("day_000"))].iloc[0]
    res = {}
    for k, v in sc.items():
        if k.startswith("t_") or k == "has_full_pipeline":
            continue
        pv = row[k]
        if isinstance(v, str):
            res[k] = {"new": v, "parent": pv, "equal": v == pv}
        else:
            res[k] = {"new": v, "parent": float(pv), "abs_diff": abs(v - float(pv))}
    res["base_sha"] = [compute_hash_fingerprint(days[0])[:16], row.base_sha]
    res["clone_sha"] = [compute_hash_fingerprint(cl)[:16], row.clone_sha]
    res["bit_identical"] = all((r.get("abs_diff", 0.0) == 0.0 and r.get("equal", True))
                               for r in res.values() if isinstance(r, dict))
    (run / "consistency_followup.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps({k: res[k] for k in ("combined_off", "combined_on", "method_on", "bit_identical")}, indent=2, default=str))


def main():
    vocab.announce()
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--parent", required=True)
    for n in ("adjacent", "idablation"):
        p = sub.add_parser(n); p.add_argument("--run-dir", required=True)
        p.add_argument("--shard", type=int, default=0); p.add_argument("--nshards", type=int, default=1)
    p = sub.add_parser("roworder"); p.add_argument("--run-dir", required=True)
    p.add_argument("--source", choices=["weather", "flight", "baggage"], required=True)
    p.add_argument("--chunk", type=int, default=None)
    p = sub.add_parser("negatives"); p.add_argument("--run-dir", required=True)
    p.add_argument("--source", choices=["flight", "baggage"], required=True)
    p.add_argument("--chunk", type=int, default=None)
    p = sub.add_parser("consistency"); p.add_argument("--run-dir", required=True)
    a = ap.parse_args()
    {"init": phase_init, "adjacent": phase_adjacent, "roworder": phase_roworder,
     "idablation": phase_idablation, "negatives": phase_negatives,
     "consistency": phase_consistency}[a.cmd](a)


if __name__ == "__main__":
    main()
