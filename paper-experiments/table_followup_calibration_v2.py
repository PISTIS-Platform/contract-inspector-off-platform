#!/usr/bin/env python3
"""Even/odd-day calibration split on weather, thresholds on vao_on / vao_off over all references."""
import argparse, json
from pathlib import Path
import numpy as np, pandas as pd
from table_followup_calibration import day, thresholds


def compute(run: Path, parent: Path) -> pd.DataFrame:
    """Calibration-split table from the parent run's CSVs and the follow-up's adjacent-pair CSV."""
    pos = pd.concat([pd.read_csv(parent / f"positives_{e}.csv") for e in "AB"])
    pos = pos[pos.source == "weather"].copy()
    pos["ld"] = pos["rd"] = pos.sample_id.map(day)
    pos["vkey"] = np.where(pos.kind == "full", "full", pos.variant)
    nb = pd.read_csv(parent / "negatives_weather_base.csv"); nb["ld"], nb["rd"] = nb.left_id.map(day), nb.right_id.map(day)
    nb["origin"] = "parent_base_vs_other_base"
    adj = pd.read_csv(run / "weather_reference_adjacent.csv"); adj["ld"], adj["rd"] = adj.left_day, adj.right_day
    ab = adj[adj.pair_type == "base_adjacent"].copy(); ab["origin"] = "adjacent_base_vs_base"
    ac = adj[adj.pair_type == "clone_vs_adjacent_base"].copy(); ac["vkey"] = ac.variant; ac["origin"] = "adjacent_clone_vs_base"
    pc = pd.concat([pd.read_csv(parent / f"negatives_{g}.csv") for g in ("weather_clones", "weather_partials", "weather_partials_AC")])
    pc = pc[pc.encoding.isin(["A", "B"])].copy(); pc["ld"], pc["rd"] = pc.left_id.map(day), pc.right_id.map(day)
    pc["vkey"] = pc.neg_type.map(lambda s: "full" if s.startswith("fullclone") else s.split("_")[1]); pc["origin"] = "parent_clone_vs_other_base"

    rows = []
    for enc in "AB":
        for vk in ("full", "precautious", "careful", "greedy"):
            P = pos[(pos.encoding == enc) & (pos.vkey == vk)]
            refs = pd.concat([nb, ab, pc[(pc.encoding == enc) & (pc.vkey == vk)], ac[(ac.encoding == enc) & (ac.vkey == vk)]])
            refs = refs.drop_duplicates(subset=["ld", "rd", "origin"])
            for m in ("vao_on", "vao_off"):
                for scheme in ("both_days", "left_day"):
                    for tp, name in ((0, "even->odd"), (1, "odd->even")):
                        if scheme == "both_days":
                            rtr = refs[(refs.ld % 2 == tp) & (refs.rd % 2 == tp)]; rte = refs[(refs.ld % 2 != tp) & (refs.rd % 2 != tp)]
                        else:
                            rtr = refs[refs.ld % 2 == tp]; rte = refs[refs.ld % 2 != tp]
                        xp_tr, xp_te = P[P.ld % 2 == tp][m].to_numpy(), P[P.ld % 2 != tp][m].to_numpy()
                        xr_tr, xr_te = rtr[m].to_numpy(), rte[m].to_numpy()
                        mid, you, _ = thresholds(xp_tr, xr_tr)
                        for rule, t in (("midpoint", mid), ("youden", you)):
                            rows.append({"encoding": enc, "clone_kind": vk, "metric": m, "scheme": scheme, "split": name,
                                         "rule": rule, "threshold": t, "n_pos_train": len(xp_tr), "n_ref_train": len(xr_tr),
                                         "n_pos_test": len(xp_te), "n_ref_test": len(xr_te),
                                         "train_max_ref": xr_tr.max(), "train_min_pos": xp_tr.min(),
                                         "test_max_ref": xr_te.max(), "test_min_pos": xp_te.min(),
                                         "test_gap_minpos_minus_maxref": xp_te.min() - xr_te.max(),
                                         "test_TPR": (xp_te >= t).mean(), "test_ref_rate": (xr_te >= t).mean(),
                                         "test_n_ref_flagged": int((xr_te >= t).sum())})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run-dir", required=True)
    ap.add_argument("--parent", default=None, help="parent table_regen run dir (default: manifest.json parent_run)")
    ap.add_argument("--out-dir", default=None, help="where to write calibration_split_v2.csv (default: run dir; manifest only updated then)")
    a = ap.parse_args()
    run = Path(a.run_dir)
    parent = Path(a.parent) if a.parent else Path(__file__).resolve().parent / json.loads((run / "manifest.json").read_text())["parent_run"]
    out_dir = Path(a.out_dir) if a.out_dir else run
    out = compute(run, parent); out.to_csv(out_dir / "calibration_split_v2.csv", index=False)
    pd.set_option("display.width", 250)
    print(out[out.rule == "midpoint"][["encoding","clone_kind","metric","scheme","split","threshold","n_ref_train","n_ref_test","test_TPR","test_ref_rate","test_max_ref","test_min_pos"]].round(4).to_string())
    if out_dir == run:
        m = json.loads((run / "manifest.json").read_text())
        m["tasks"]["4b"] = "calibration_split_v2.csv (vao_on/vao_off, all references, both_days and left_day schemes; table_followup_calibration_v2.py)"
        (run / "manifest.json").write_text(json.dumps(m, indent=2))


if __name__ == "__main__":
    main()
