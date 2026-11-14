"""Persist the datasets created during an experiment, for reproducibility."""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Iterable

from .loader import Dataset


def write_manifest(run_dir: Path, params: dict, counts: dict,
                   extra: dict | None = None) -> Path:
    """Write manifest.json (timestamp, parameters, counts) into a run directory."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        "params": params,
        "counts": counts,
    }
    if extra:
        manifest["summary"] = extra
    path = run_dir / "manifest.json"
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)
    return path


def _safe_name(s: str) -> str:
    for a, b in (("/", "__"), ("\\", "__"), ("<", ""), (">", ""), (":", "_"), (" ", "_")):
        s = s.replace(a, b)
    return s


def _serializable(ds: Dataset) -> dict:
    out = {"source_path": ds.source_path, "modality": ds.modality.value, "data": ds.data}
    unit_meta = getattr(ds, "unit_meta", None)
    if unit_meta:
        out["unit_meta"] = unit_meta
    return out


def save_dataset(ds: Dataset, datasets_dir: Path, name: str | None = None) -> Path:
    """Write one dataset to ``datasets_dir/<name>.json``."""
    datasets_dir = Path(datasets_dir)
    datasets_dir.mkdir(parents=True, exist_ok=True)
    path = datasets_dir / f"{_safe_name(name or ds.source_path)}.json"
    with open(path, "w") as f:
        json.dump(_serializable(ds), f, default=str)
    return path


def save_datasets_jsonl(datasets: Iterable[Dataset], path: Path) -> int:
    """Write many datasets to one JSONL (deduplicated by source_path)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    n = 0
    with open(path, "w") as f:
        for ds in datasets:
            if ds is None or ds.source_path in seen:
                continue
            seen.add(ds.source_path)
            f.write(json.dumps(_serializable(ds), default=str) + "\n")
            n += 1
    return n
