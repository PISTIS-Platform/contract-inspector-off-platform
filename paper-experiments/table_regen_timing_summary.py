#!/usr/bin/env python3
"""Median / IQR per stage from a table_regen timing.csv."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

run = Path(sys.argv[1])
d = pd.read_csv(run / "timing.csv")
rows = []
for (src, case), g in d.groupby(["source", "case"], sort=False):
    r = {"source": src, "case": case, "reps": len(g), "n_rows": g.n_rows.iloc[0],
         "n_cols_base": g.n_cols_base.iloc[0], "n_cols_clone": g.n_cols_clone.iloc[0],
         "method_off": g.method_off.iloc[0], "method_on": g.method_on.iloc[0]}
    for col in ("total_off_s", "total_on_s", "units_on_s", "tz_on_s", "hash_on_s", "hash_off_s"):
        v = g[col].dropna().to_numpy(float) * 1000
        q1, med, q3 = np.percentile(v, [25, 50, 75]) if len(v) else (np.nan,) * 3
        r[col.replace("_s", "_ms") + "_med"] = med
        r[col.replace("_s", "_ms") + "_iqr"] = q3 - q1
    r["defence_overhead_ms"] = r["units_on_ms_med"] + r["tz_on_ms_med"]
    r["defence_overhead_pct_of_total_on"] = 100 * r["defence_overhead_ms"] / r["total_on_ms_med"]
    r["on_vs_off_total_ratio"] = r["total_on_ms_med"] / r["total_off_ms_med"]
    rows.append(r)
out = pd.DataFrame(rows)
out.to_csv(run / "timing_summary.csv", index=False)
pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40)
print(out.round(1).to_string())
