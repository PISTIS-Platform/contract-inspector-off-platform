"""Shared helpers for the vocabulary loader: errors, lookup order, TOML reading."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]

ENV_VARS = {"units": "INSPECTOR_UNITS_VOCAB", "timezones": "INSPECTOR_TZ_VOCAB"}
FILENAMES = {"units": "units.toml", "timezones": "timezones.toml"}
KINDS = tuple(FILENAMES)
MODES = ("extend", "replace")


class VocabularyError(ValueError):
    """A vocabulary file is missing, unreadable or invalid."""


def default_data_dir() -> Path:
    """$PISTIS_DATA_DIR, else a ``dataset/`` folder next to the directory containing ``inspector``."""
    env = os.environ.get("PISTIS_DATA_DIR")
    return Path(env) if env else PROJECT_ROOT.parent / "dataset"


def default_path(kind: str) -> Path:
    return HERE / FILENAMES[kind]


def read_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        raise VocabularyError(f"vocabulary file not found: {path}") from None
    except tomllib.TOMLDecodeError as e:
        raise VocabularyError(f"{path}: not valid TOML: {e}") from None


def find_user_file(kind: str, explicit: str | os.PathLike | None = None) -> tuple[Path | None, str]:
    """Explicit path, then the INSPECTOR_*_VOCAB variable, then <data dir>/vocab/; None means the shipped default."""
    if explicit is not None:
        return Path(explicit), "explicit path"
    env = os.environ.get(ENV_VARS[kind])
    if env:
        return Path(env), f"environment variable {ENV_VARS[kind]}"
    cand = default_data_dir() / "vocab" / FILENAMES[kind]
    if cand.is_file():
        return cand, "data/vocab next to the data"
    return None, "shipped default"


def check_keys(doc: dict, allowed: set[str], where: str, errors: list[str]) -> None:
    for k in doc:
        if k not in allowed:
            errors.append(f"{where}: unknown key {k!r} (allowed: {', '.join(sorted(allowed))})")


def doc_mode(doc: dict, where: str, errors: list[str]) -> str:
    mode = doc.get("mode", "extend")
    if mode not in MODES:
        errors.append(f"{where}: mode must be 'extend' or 'replace', got {mode!r}")
    return mode


def check_mode(mode: str) -> str:
    if mode not in MODES:
        raise VocabularyError(f"mode must be 'extend' or 'replace', got {mode!r}")
    return mode


def raise_if(errors: list[str], path: str) -> None:
    if errors:
        raise VocabularyError(f"{path}: {len(errors)} problem(s):\n  - " + "\n  - ".join(errors))
