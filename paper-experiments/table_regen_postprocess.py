#!/usr/bin/env python3
"""Post-processing of a ``table_regen`` run: derived columns, per-source x encoding positives-vs-negatives discrimination summary, identifier-effect diagnostic."""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

TAU = 0.5
METRICS = ["final_off", "combined_off", "combined_on", "final_on", "vao_off", "vao_on"]


def add_partial(df: pd.DataFrame, side: str) -> pd.DataFrame:
    """S_partial = gated / schema_recall (explicit column, assert r > 0)."""
    for d in ("off", "on"):
        if f"gated_{d}" not in df or f"schema_recall_{d}" not in df:
            continue
        ok = df[f"gated_{d}"].notna()
        r = df[f"schema_recall_{d}"]
        if side == "positives":
            assert (r[ok] > 0).all(), f"schema_recall == 0 in {side} ({d})"
        df[f"partial_reuse_{d}"] = (df[f"gated_{d}"] / r.where(r > 0)).where(ok)
    return df


def load(run: Path):
    pos = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(str(run / "positives_[ABC].csv")))
                     + [str(run / "positives_baggage.csv")] if Path(f).exists()], ignore_index=True)
    neg = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(str(run / "negatives_*.csv")))
                     if "_all" not in f], ignore_index=True)
    pos = add_partial(pos, "positives")
    neg = add_partial(neg, "negatives")
    pos["group"] = np.where(pos.source == "baggage", "baggage_" + pos.view.fillna(""), pos.source)
    return pos, neg


def classify_neg(t: str) -> tuple[str, str]:
    """(kind, variant): kind in base|full|partial."""
    if "partial" in t:
        for v in ("precautious", "careful", "greedy"):
            if v in t:
                return "partial", v
        return "partial", "?"
    if "clone" in t:
        return "full", ""
    return "base", ""


def pair_class(t: str) -> str:
    """User-facing label."""
    if t.startswith("crosssource"):
        return "non_clone_cross_source"
    if "crossview" in t:
        return "non_clone_cross_view"
    if "half" in t:
        return "same_source_other_half"
    if "disjoint" in t:
        return "same_source_disjoint_sample"
    return "same_source_different_day"


def neg_group(row) -> str:
    if row["source"].startswith("baggage_"):
        return row["source"]
    if row["source"] == "baggage":
        return "baggage_" + str(row["right_id"])
    return row["source"]


def best_threshold(p: np.ndarray, n: np.ndarray):
    xs = np.unique(np.concatenate([p, n]))
    best = (-1.0, None)
    cands = np.concatenate([[xs.min() - 1e-9], (xs[:-1] + xs[1:]) / 2, [xs.max() + 1e-9]])
    for t in cands:
        bal = 0.5 * ((p >= t).mean() + (n < t).mean())
        if bal > best[0]:
            best = (bal, float(t))
    return best


def summarize(pos, neg) -> pd.DataFrame:
    neg = neg.copy()
    neg["group"] = neg.apply(neg_group, axis=1)
    neg["pair_class"] = neg.neg_type.map(pair_class)
    cls = neg.neg_type.map(classify_neg)
    neg["nkind"] = [c[0] for c in cls]
    neg["nvariant"] = [c[1] for c in cls]
    rows = []
    for (grp, enc, kind, variant), P in pos.groupby(["group", "encoding", "kind", "variant"]):
        N = neg[(neg.group == grp) & ((neg.encoding == enc) | (neg.encoding == "none"))]
        if kind == "full":
            N = N[N.nkind.isin(["base", "full"])]
        else:
            Np = N[(N.nkind == "partial")]
            Np_v = Np[Np.nvariant == variant]
            N = pd.concat([N[N.nkind == "base"], Np_v if len(Np_v) else Np])
        for m in METRICS:
            p = P[m].dropna().to_numpy(float)
            n = N[m].dropna().to_numpy(float)
            r = {"group": grp, "encoding": enc, "kind": kind, "variant": variant, "metric": m,
                 "n_pos": len(p), "n_other": len(n)}
            if len(p) and len(n):
                try:
                    auc = roc_auc_score(np.r_[np.ones(len(p)), np.zeros(len(n))], np.r_[p, n])
                except ValueError:
                    auc = np.nan
                bal, thr = best_threshold(p, n)
                r.update({"pos_min": p.min(), "pos_mean": p.mean(), "pos_max": p.max(),
                          "other_min": n.min(), "other_mean": n.mean(), "other_max": n.max(),
                          "pos_ge_tau": int((p >= TAU).sum()), "other_ge_tau": int((n >= TAU).sum()),
                          "pos_eq_1": int((p == 1.0).sum()), "other_eq_1": int((n == 1.0).sum()),
                          "auc": auc, "best_thr": thr, "balanced_acc_at_best": bal,
                          "margin_minpos_minus_maxother": p.min() - n.max(), "margin_1_minus_maxother": 1.0 - n.max(),
                          "other_pair_types": ";".join(sorted(N.neg_type.unique()))})
            rows.append(r)
    return pd.DataFrame(rows)


def gap_table(pos, neg) -> pd.DataFrame:
    """Weather same-source different-day pairs stratified by calendar |gap|."""
    import datetime as dt
    dates = {}
    for sid in pos[(pos.source == "weather")].sample_id.unique():
        _, idx, d = sid.split("_")
        dates[int(idx)] = dt.datetime.strptime(d, "%Y%m%d")
    w = neg[neg.source == "weather"].copy()
    w["pair_class"] = w.neg_type.map(pair_class)
    w["gap_days"] = [abs((dates[int(a[1:])] - dates[int(b[1:])]).days) for a, b in zip(w.left_id, w.right_id)]
    bins = [0, 1, 7, 30, 10_000]
    w["gap_bin"] = pd.cut(w.gap_days, bins=bins, labels=["1", "2-7", "8-30", ">30"])
    cols = [m for m in METRICS if m in w]
    rows = []
    for (nt, enc, gb), G in w.groupby(["neg_type", "encoding", "gap_bin"], observed=True):
        r = {"neg_type": nt, "encoding": enc, "gap_bin": gb, "n_pairs": len(G)}
        for m in cols:
            v = G[m].dropna()
            r.update({f"{m}_n": len(v), f"{m}_mean": v.mean() if len(v) else np.nan,
                      f"{m}_min": v.min() if len(v) else np.nan, f"{m}_max": v.max() if len(v) else np.nan})
        rows.append(r)
    return pd.DataFrame(rows)


def counts_table(pos) -> pd.DataFrame:
    g = pos.groupby(["group", "encoding", "kind", "variant"])
    out = g.agg(n=("F", "size"), F=("F", "first"), U=("U", "first"), T=("T", "first"),
                n_cols_clone=("n_cols_clone", "first"), n_rows=("n_rows_base", "first"),
                n_cols_attacked=("n_cols_attacked", "first"),
                det_final_off=("detected_final_off", "sum"), det_combined_off=("detected_combined_off", "sum"),
                det_final_on=("detected_final_on", "sum"), det_combined_on=("detected_combined_on", "sum"),
                mean_final_off=("final_off", "mean"), mean_combined_off=("combined_off", "mean"),
                min_combined_off=("combined_off", "min"), max_combined_off=("combined_off", "max"),
                mean_final_on=("final_on", "mean"), mean_combined_on=("combined_on", "mean"),
                mean_schema_recall_off=("schema_recall_off", "mean"),
                hash_match_on=("method_on", lambda s: int((s == "hash_match").sum())))
    return out.reset_index()


def identifier_effect(run: Path) -> dict:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import table_regen_experiment as T
    from inspector.loader import Dataset
    from inspector.engine import SimilarityPipeline
    import re

    vao = SimilarityPipeline(alpha=0.5, threshold=T.TAU, value_aware_only=True)
    w = T.load_weather()
    base0, base5 = w[0], w[5]
    res: dict = {}

    def drop(ds, cols):
        return Dataset(data=[{k: v for k, v in r.items() if k not in cols} for r in ds.data],
                       modality=ds.modality, source_path=ds.source_path + ".dropids",
                       unit_meta={k: u for k, u in ds.unit_meta.items() if k not in cols})

    def per_column(a, b):
        rep = vao.compare(a, b)
        agg: dict = {}
        for path, s in rep.field_similarities.items():
            col = re.sub(r"^.*?\]\.?", "", path) if "]" in path else path
            agg.setdefault(col, []).append(s)
        return rep, {c: {"n_paths": len(v), "mean_value_sim": float(np.mean(v))} for c, v in agg.items()}

    for enc in ("A", "B"):
        clone0 = T.make_full_clone(base0, "weather", enc)
        for label, left, right in (("clone_d0_vs_base_d0 (true clone)", clone0, base0),
                                   ("clone_d0_vs_base_d5 (non-clone, other day)", clone0, base5)):
            rep, cols = per_column(left, right)
            ids = ["cell_id", "obs_date"]
            rep2 = vao.compare(drop(left, ids), drop(right, ids))
            res[f"weather_enc{enc}__{label}"] = {
                "jaccard": rep.jaccard_score, "value": rep.value_score, "combined": rep.combined_score,
                "n_shared_paths": len(rep.shared_paths),
                "shared_columns_value_sim": cols,
                "combined_after_dropping_cell_id_and_obs_date_from_both": rep2.combined_score,
                "jaccard_after_drop": rep2.jaccard_score, "value_after_drop": rep2.value_score,
            }
    (run / "identifier_effect.json").write_text(json.dumps(res, indent=2))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--identifier-effect", action="store_true")
    a = ap.parse_args()
    run = Path(a.run_dir)
    pos, neg = load(run)
    pos.to_csv(run / "positives_all.csv", index=False)
    neg.to_csv(run / "negatives_all.csv", index=False)
    summ = summarize(pos, neg)
    summ.to_csv(run / "discrimination_summary.csv", index=False)
    counts_table(pos).to_csv(run / "table2_table3_counts.csv", index=False)
    gap_table(pos, neg).to_csv(run / "weather_gap_stratified.csv", index=False)
    neg.assign(pair_class=neg.neg_type.map(pair_class)).to_csv(run / "negatives_all.csv", index=False)
    print(f"positives {len(pos)}  negatives {len(neg)}  summary rows {len(summ)}")
    if a.identifier_effect:
        print(json.dumps(identifier_effect(run), indent=1)[:4000])


if __name__ == "__main__":
    main()
