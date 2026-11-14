#!/usr/bin/env python3
"""Task 4: even/odd-day calibration split on weather (CSV-only, no scoring)."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

METRICS = ["combined_on", "final_on", "final_off", "combined_off"]


def day(s):
    s = str(s)
    return int(s.split("_")[1]) if s.startswith("day_") else int(s[1:])


def thresholds(pos, ref):
    mid = (ref.max() + pos.min()) / 2 if len(ref) and len(pos) else np.nan
    cand = np.unique(np.concatenate([pos, ref]))
    cand = np.concatenate([[cand.min() - 1e-9], (cand[:-1] + cand[1:]) / 2, [cand.max() + 1e-9]])
    best, bj = np.nan, -2
    for t in cand:
        j = (pos >= t).mean() - (ref >= t).mean()
        if j >= bj:
            best, bj = t, j
    return mid, best, bj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--parent", default=None, help="parent table_regen run dir (default: manifest.json parent_run)")
    ap.add_argument("--out-dir", default=None, help="where to write calibration_split.csv (default: run dir)")
    a = ap.parse_args()
    run = Path(a.run_dir)
    import json
    parent = Path(a.parent) if a.parent else Path(__file__).resolve().parent / json.loads((run / "manifest.json").read_text())["parent_run"]
    out_dir = Path(a.out_dir) if a.out_dir else run
    pos = pd.concat([pd.read_csv(parent / f"positives_{e}.csv") for e in "AB"])
    pos = pos[pos.source == "weather"].copy()
    pos["day"] = pos.sample_id.map(day)
    pos["vkey"] = np.where(pos.kind == "full", "full", pos.variant)

    nb = pd.read_csv(parent / "negatives_weather_base.csv")
    nb["day"] = nb.left_id.map(day)
    nb["origin"] = "parent_base_vs_other_base"
    adj = pd.read_csv(run / "weather_reference_adjacent.csv")
    ab = adj[adj.pair_type == "base_adjacent"].copy()
    ab["day"] = ab.left_day
    ab["origin"] = "adjacent_base_vs_base"
    ac = adj[adj.pair_type == "clone_vs_adjacent_base"].copy()
    ac["day"] = ac.left_day
    ac["origin"] = "adjacent_clone_vs_base"
    pc = pd.concat([pd.read_csv(parent / f"negatives_{g}.csv") for g in
                    ("weather_clones", "weather_partials", "weather_partials_AC")])
    pc = pc[pc.encoding.isin(["A", "B"])].copy()
    pc["day"] = pc.left_id.map(day)
    pc["origin"] = "parent_clone_vs_other_base"
    pc["vkey"] = pc.neg_type.map(lambda s: "full" if s.startswith("fullclone") else s.split("_")[1])
    ac["vkey"] = ac.variant

    rows = []
    for enc in ("A", "B"):
        for vk in ("full", "precautious", "careful", "greedy"):
            P = pos[(pos.encoding == enc) & (pos.vkey == vk)]
            refs = pd.concat([nb, ab,
                              pc[(pc.encoding == enc) & (pc.vkey == vk)],
                              ac[(ac.encoding == enc) & (ac.vkey == vk)]])
            for m in METRICS:
                for train_par, name in ((0, "train_even_test_odd"), (1, "train_odd_test_even")):
                    ptr, pte = P[P.day % 2 == train_par], P[P.day % 2 != train_par]
                    rtr, rte = refs[refs.day % 2 == train_par], refs[refs.day % 2 != train_par]
                    xp_tr, xp_te = ptr[m].dropna().to_numpy(), pte[m].dropna().to_numpy()
                    xr_tr, xr_te = rtr[m].dropna().to_numpy(), rte[m].dropna().to_numpy()
                    mid, you, j = thresholds(xp_tr, xr_tr)
                    for rule, t in (("midpoint", mid), ("youden", you)):
                        rows.append({
                            "encoding": enc, "clone_kind": vk, "metric": m, "split": name, "rule": rule,
                            "threshold": t, "train_max_ref": xr_tr.max(), "train_min_pos": xp_tr.min(),
                            "train_margin": xp_tr.min() - xr_tr.max(),
                            "n_pos_train": len(xp_tr), "n_ref_train": len(xr_tr),
                            "n_pos_test": len(xp_te), "n_ref_test": len(xr_te),
                            "test_max_ref": xr_te.max(), "test_min_pos": xp_te.min(),
                            "test_TPR": (xp_te >= t).mean(), "test_FPR": (xr_te >= t).mean(),
                            "test_n_FP": int((xr_te >= t).sum()),
                            "all_max_ref": np.concatenate([xr_tr, xr_te]).max(),
                            "all_min_pos": np.concatenate([xp_tr, xp_te]).min(),
                        })
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "calibration_split.csv", index=False)
    pd.set_option("display.width", 250)
    print(out[(out.split == "train_even_test_odd") & (out.rule == "midpoint")][
        ["encoding", "clone_kind", "metric", "threshold", "train_margin", "test_TPR", "test_FPR", "n_ref_test"]
    ].round(4).to_string())


if __name__ == "__main__":
    main()
