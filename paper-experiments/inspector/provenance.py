"""Per-run provenance capture."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


SOURCE_GLOBS = (
    "inspector/**/*.py",
    "inspector/vocab/*.toml",
    "requirements.txt",
)

DATA_GLOBS = (
    "../dataset/**/*.csv",
    "../dataset/**/*.xlsx",
)

TRACKED_PACKAGES = (
    "numpy", "pandas", "scikit-learn", "scipy", "torch",
    "sentence-transformers", "mmh3", "bitarray", "Levenshtein",
    "matplotlib", "seaborn", "openpyxl", "pint", "tifffile",
)


def _sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _glob_relative(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for pat in patterns:
        for p in sorted(root.glob(pat)):
            if not p.is_file():
                continue
            if "__pycache__" in p.parts:
                continue
            out.append(p)
    return out


def _git(cmd: list[str], cwd: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git"] + cmd, cwd=str(cwd),
            capture_output=True, text=True, timeout=10, check=False,
        )
        if out.returncode != 0:
            return None
        return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


@dataclass
class CapturedRun:
    """Lightweight view of a run's provenance for diffing."""
    output_dir: Path
    timestamp: str
    args: dict
    env: dict
    git: dict
    source_hashes: dict[str, str]
    data_hashes: dict[str, str]


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _vocabulary_info(v) -> dict:
    files = {s: _sha256_file(Path(s)) for s in v.sources if s != "default" and Path(s).is_file()}
    return {"description": v.description, "user_files_sha256": files}


def _capture_env() -> dict:
    env: dict = {
        "python_version": sys.version,
        "python_executable": os.path.basename(sys.executable),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }
    env["packages"] = {name: _package_version(name) for name in TRACKED_PACKAGES}
    try:
        from .engine import select_best_device
        env["inspector_device"] = select_best_device()
    except Exception:
        env["inspector_device"] = "unknown"
    from . import timezones, units
    env["vocabulary"] = {"units": _vocabulary_info(units.ACTIVE_VOCABULARY),
                         "timezones": _vocabulary_info(timezones.ACTIVE_VOCABULARY)}
    return env


def _capture_git(implementation_root: Path) -> dict:
    branch = _git(["branch", "--show-current"], implementation_root)
    commit = _git(["rev-parse", "HEAD"], implementation_root)
    status = _git(["status", "--porcelain"], implementation_root)
    if commit is None:
        return {"available": False}
    return {
        "available": True,
        "branch": branch or "",
        "commit": commit,
        "dirty": bool(status),
        "dirty_files": [line for line in (status or "").splitlines()],
    }


def _capture_sources(implementation_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for src in _glob_relative(implementation_root, SOURCE_GLOBS):
        rel = src.relative_to(implementation_root)
        digest = _sha256_file(src)
        hashes[str(rel)] = digest
    return hashes


def _capture_data(implementation_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    data_dir = os.environ.get("PISTIS_DATA_DIR")
    if data_dir:
        root = Path(data_dir).resolve()
        for pat in ("**/*.csv", "**/*.xlsx", "**/*.tif", "**/*.tiff"):
            for f in sorted(root.glob(pat)):
                hashes[f.relative_to(root).as_posix()] = _sha256_file(f)
        return hashes
    for f in _glob_relative(implementation_root, DATA_GLOBS):
        key = str(f.resolve().relative_to(implementation_root.parent.resolve()))
        hashes[key] = _sha256_file(f)
    return hashes


def capture(
    output_dir: Path,
    args: dict,
    argv: list[str],
    implementation_root: Path,
) -> CapturedRun:
    """Write a complete provenance snapshot into ``output_dir/provenance/``."""
    provenance_dir = output_dir / "provenance"
    provenance_dir.mkdir(parents=True, exist_ok=True)

    ts = _dt.datetime.now().isoformat(timespec="seconds")

    args_dump = {
        "argv": argv,
        "parsed": {k: (str(v) if isinstance(v, Path) else v) for k, v in args.items()},
        "cwd": os.path.relpath(os.getcwd(), implementation_root.resolve()),
    }
    env = _capture_env()
    git_info = _capture_git(implementation_root)
    source_hashes = _capture_sources(implementation_root)
    data_hashes = _capture_data(implementation_root)

    (provenance_dir / "args.json").write_text(json.dumps(args_dump, indent=2))
    (provenance_dir / "env.json").write_text(json.dumps(env, indent=2))
    (provenance_dir / "git.json").write_text(json.dumps(git_info, indent=2))
    (provenance_dir / "source_hashes.json").write_text(
        json.dumps(source_hashes, indent=2, sort_keys=True)
    )
    (provenance_dir / "data_hashes.json").write_text(
        json.dumps(data_hashes, indent=2, sort_keys=True)
    )

    manifest = {
        "timestamp": ts,
        "output_dir": os.path.relpath(output_dir.resolve(), implementation_root.resolve()),
        "implementation_root": ".",
        "files": {
            "args": "provenance/args.json",
            "env": "provenance/env.json",
            "git": "provenance/git.json",
            "source_hashes": "provenance/source_hashes.json",
            "data_hashes": "provenance/data_hashes.json",
        },
        "counts": {
            "source_files": len(source_hashes),
            "data_files": len(data_hashes),
        },
    }
    (provenance_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    return CapturedRun(
        output_dir=output_dir,
        timestamp=ts,
        args=args_dump,
        env=env,
        git=git_info,
        source_hashes=source_hashes,
        data_hashes=data_hashes,
    )


def make_timestamped_output_dir(experiments_root: Path) -> Path:
    """Return a fresh ``experiments/run_YYYY-MM-DD_HHMMSS/`` path."""
    ts = _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return experiments_root / f"run_{ts}"
