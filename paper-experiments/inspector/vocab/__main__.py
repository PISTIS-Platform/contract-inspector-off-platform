"""Command line: inspect, validate and try out the unit / time vocabularies."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from . import (VocabularyError, active_timezones, active_units, default_units, detect_kind, load_timezones, load_units,
               make_registry, read_toml)


def _table(rows: list[list[str]], header: list[str]) -> str:
    cols = list(zip(header, *rows)) if rows else [(h,) for h in header]
    widths = [max(len(str(x)) for x in c) for c in cols]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    lines = [fmt.format(*header), fmt.format(*("-" * w for w in widths))]
    lines += [fmt.format(*[str(x) for x in r]) for r in rows]
    return "\n".join(lines)


def cmd_list(a) -> int:
    kinds = [a.kind] if a.kind else ["units", "timezones"]
    if "units" in kinds:
        v = active_units()
        print(f"UNITS vocabulary: {v.description}")
        rows = [[s, u, c, d, "yes" if s in v.ambiguous else "", v.alt_suffix.get(s, ""), v.origin.get(s, "default")]
                for s, (u, c, d) in v.suffix_map.items()]
        print(_table(rows, ["suffix", "source unit", "canonical", "dimension", "ambiguous", "attack alt", "from"]))
        print("\nName keywords that make an ambiguous suffix acceptable:")
        print(_table([[d, ", ".join(k), v.keyword_origin.get(d, "default")] for d, k in v.dimension_keywords.items()],
                     ["dimension", "keywords", "from"]))
        print()
    if "timezones" in kinds:
        t = active_timezones()
        print(f"TIME vocabulary: {t.description}")
        o = lambda k: t.origin.get(k, "default")
        print(_table([["reference_tz", t.reference_tz, o("reference_tz")], ["alt_tz", t.alt_tz, o("alt_tz")],
                      ["epoch min", t.epoch_min, o("epoch_min")], ["epoch max", t.epoch_max, o("epoch_max")],
                      ["epoch name keywords", ", ".join(t.name_keywords), o("name_keywords")]],
                     ["setting", "value", "from"]))
    return 0


def cmd_check(a) -> int:
    path = Path(a.file)
    try:
        doc = read_toml(path)
        kind = a.kind or detect_kind(doc)
        if kind == "units":
            before = default_units()
            v = load_units(path, a.mode, make_registry())
            added = [s for s in v.suffix_map if v.origin.get(s) != "default"]
            changed = [s for s in added if s in before.suffix_map]
            removed = [s for s in before.suffix_map if s not in v.suffix_map]
            print(f"OK  {path}  (units, {doc.get('mode', 'extend')} mode)")
            print(f"    {len(v.suffix_map)} suffixes in force: {len(added) - len(changed)} added, {len(changed)} overridden, "
                  f"{len(removed)} removed")
            if added:
                print("    from this file: " + ", ".join(added))
            for w in v.warnings:
                print(f"    warning: {w}")
        else:
            v = load_timezones(path, a.mode)
            print(f"OK  {path}  (time, {doc.get('mode', 'extend')} mode)")
            print(f"    reference_tz={v.reference_tz} alt_tz={v.alt_tz} epoch=[{v.epoch_min}, {v.epoch_max}] "
                  f"{len(v.name_keywords)} name keywords")
        return 0
    except VocabularyError as e:
        print(f"INVALID  {e}", file=sys.stderr)
        return 1


def _read_columns(path: Path, rows: int, delimiter: str | None) -> dict[str, list]:
    cols: dict[str, list] = {}
    suffix = path.suffix.lower()
    if suffix in (".jsonl", ".ndjson", ".json"):
        text = path.read_text(encoding="utf-8")
        if suffix == ".json":
            data = json.loads(text)
            recs = data if isinstance(data, list) else [data]
        else:
            recs = [json.loads(l) for l in text.splitlines() if l.strip()]
        for r in recs[:rows]:
            if isinstance(r, dict):
                for k, v in r.items():
                    cols.setdefault(k, []).append(v)
        return cols
    with open(path, newline="", encoding="utf-8-sig") as f:
        sample = f.read(8192)
        f.seek(0)
        if delimiter is None:
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","
        for i, r in enumerate(csv.DictReader(f, delimiter=delimiter)):
            if i >= rows:
                break
            for k, v in r.items():
                cols.setdefault(k, []).append(v)
    return cols


def cmd_scan(a) -> int:
    from .. import timezones, units

    path = Path(a.dataset)
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    cols = _read_columns(path, a.rows, a.delimiter)
    if not cols:
        print("no columns found (expected CSV with a header, JSON list of objects, or JSONL)", file=sys.stderr)
        return 2
    print(f"{path.name}: {len(cols)} columns, first {max(len(v) for v in cols.values())} rows")
    print(f"units vocabulary: {units.ACTIVE_VOCABULARY.description}")
    print(f"time vocabulary:  {timezones.ACTIVE_VOCABULARY.description}\n")
    n_unit = n_ts = 0
    out = []
    for name, vals in cols.items():
        nonempty = [v for v in vals if v is not None and v != ""]
        ex = units.explain_field(str(name))
        unit_txt = "-"
        if ex["detected"]:
            num = sum(1 for v in nonempty if units._as_number(v) is not None)
            share = f"{num} of {len(nonempty)} values numeric" if nonempty else "no values"
            if nonempty and num == 0:
                unit_txt = f"NOT USED: name matches ({ex['reason']}) but no value is numeric"
            else:
                n_unit += 1
                unit_txt = (f"UNIT {ex['unit']} -> {ex['canonical']} ({ex['dimension']}); {ex['reason']}; {share}"
                            + ("; non-numeric values are left untouched" if num < len(nonempty) else ""))
        else:
            unit_txt = f"no unit: {ex['reason']}"
        tz = timezones.explain_column(str(name), vals)
        if tz["kind"]:
            n_ts += 1
            tz_txt = f"TIMESTAMP ({tz['kind']}): {tz['reason']}"
        else:
            tz_txt = f"no timestamp: {tz['reason']}"
        out.append((name, unit_txt, tz_txt))
    for name, u, t in out:
        print(f"{name}\n    {u}\n    {t}")
    print(f"\n{n_unit} unit-bearing and {n_ts} timestamp column(s) of {len(cols)}.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m inspector.vocab", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="print the active vocabulary and where each entry comes from")
    p.add_argument("--kind", choices=["units", "timezones"])
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("check", help="validate a user vocabulary file")
    p.add_argument("file")
    p.add_argument("--kind", choices=["units", "timezones"])
    p.add_argument("--mode", choices=["extend", "replace"], help="override the file's own mode")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("scan", help="show, per column of a dataset, what is detected as a unit / timestamp and why")
    p.add_argument("dataset")
    p.add_argument("--rows", type=int, default=2000, help="rows to read (default 2000)")
    p.add_argument("--delimiter", help="CSV delimiter (default: detected)")
    p.set_defaults(fn=cmd_scan)
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except VocabularyError as e:
        print(f"INVALID  {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
