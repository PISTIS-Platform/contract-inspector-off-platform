#!/usr/bin/env python3
"""Re-score 3 parent positive + 3 parent reference rows with the FINAL harness and compare exactly (float equality via csv/float(), timing columns excluded)."""
import csv, json, sys
from pathlib import Path
import table_regen_experiment as T
from partial_clone_experiment import baggage_selection, weather_selection

P = Path(sys.argv[1])
pipes = T.make_pipes(); T.warm(pipes)
rows = lambda f: list(csv.DictReader(open(P / f)))
W = T.load_weather(); wsel = weather_selection()
bags = T.load_baggage(); bsel = baggage_selection(T.DATA_DIR)
day = lambda s: int(s.split("_")[1]) if s.startswith("day_") else int(s[1:])

def parent_row(f, **kw):
    for r in rows(f):
        if all(r[k] == v for k, v in kw.items()):
            return r
    raise KeyError((f, kw))

cases = []
r = parent_row("positives_B.csv", source="weather", kind="full", sample_id="day_000_20230801")
cases.append(("pos weather d0 full B", r, T.score_pair(W[0], T.make_full_clone(W[0], "weather", "B"), pipes)))
r = parent_row("positives_A.csv", source="weather", kind="partial", variant="precautious", sample_id=[x["sample_id"] for x in rows("positives_A.csv") if x["sample_id"].startswith("day_060")][0])
cl = T.make_full_clone(W[60], "weather", "A")
cases.append(("pos weather d60 precautious A", r, T.score_pair(W[60], T.make_partial(cl, wsel, "precautious", "weather", "A"), pipes)))
r = parent_row("positives_baggage.csv", source="baggage", view="arrival", kind="partial", variant="greedy", encoding="B")
b = bags["arrival"]; cl = T.make_full_clone(b, "baggage", "B")
cases.append(("pos baggage arrival greedy", r, T.score_pair(b, T.make_partial(cl, bsel["arrival_baggage"], "greedy", "baggage", "B"), pipes)))
r = parent_row("negatives_weather_base.csv", left_id="d000", right_id="d071")
cases.append(("ref weather base d000-d071", r, T.score_pair(W[0], W[71], pipes)))
r = parent_row("negatives_weather_clones.csv", encoding="A", left_id="d000", partner_rank="0")
cl = T.make_full_clone(W[0], "weather", "A")
cases.append(("ref weather fullclone A d000 vs " + r["right_id"], r, T.score_pair(cl, W[day(r["right_id"])], pipes)))
r = parent_row("negatives_misc.csv", neg_type="baggage_crossview_base_vs_base", left_id="arrival", right_id="departure")
cases.append(("ref baggage crossview arrival-departure", r, T.score_pair(bags["arrival"], bags["departure"], pipes)))

out = {}
for name, pr, new in cases:
    bad = {}
    n = 0
    for k, v in new.items():
        if k.startswith("t_") or k not in pr:
            continue
        n += 1
        same = (v == pr[k]) if isinstance(v, str) else (
            (v != v and pr[k] in ("nan", "")) or v == float(pr[k]))
        if not same:
            bad[k] = {"new": v, "parent": pr[k]}
    out[name] = {"columns_compared": n, "bit_identical": not bad, "mismatches": bad}
    print(name, n, "IDENTICAL" if not bad else bad, flush=True)
out["all_identical"] = all(v["bit_identical"] for v in out.values())
(P / "provenance" / "reproduce_check.json").write_text(json.dumps(out, indent=2))
