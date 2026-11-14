"""Editable vocabularies for unit and timestamp detection."""

from __future__ import annotations

from pathlib import Path

from ._common import KINDS, VocabularyError, find_user_file, read_toml
from ._timezones import TimezoneVocabulary, default_timezones, load_timezones, validate_timezones
from ._units import UnitsVocabulary, default_units, load_units, make_registry, validate_units

__all__ = [
    "VocabularyError", "UnitsVocabulary", "TimezoneVocabulary", "load_vocabulary", "activate", "active_units",
    "active_timezones", "detect_kind", "default_units", "default_timezones", "find_user_file", "validate_units",
    "validate_timezones", "make_registry", "announce",
]


def detect_kind(doc: dict) -> str:
    """Decide from the content of a TOML document whether it is a units or a time vocabulary."""
    if "suffix" in doc or "dimension" in doc or "remove" in doc:
        return "units"
    if "reference_tz" in doc or "alt_tz" in doc or "epoch" in doc:
        return "timezones"
    raise VocabularyError("cannot tell if this is a units or a time vocabulary; pass kind='units' or 'timezones'")


def load_vocabulary(path, kind: str | None = None, mode: str | None = None, registry=None):
    """Load a vocabulary file explicitly (highest priority in the lookup order)."""
    if kind is None:
        kind = detect_kind(read_toml(Path(path)))
    if kind == "units":
        return load_units(path, mode, registry)
    if kind == "timezones":
        return load_timezones(path, mode)
    raise VocabularyError(f"unknown vocabulary kind {kind!r} (expected one of {KINDS})")


def active_units(registry=None) -> UnitsVocabulary:
    """The vocabulary in force at import time (env var, data dir or shipped default)."""
    return load_units(None, None, registry)


def active_timezones() -> TimezoneVocabulary:
    return load_timezones(None, None)


def announce() -> None:
    """Print a line for each vocabulary in force that is not the shipped default."""
    from .. import timezones, units

    for v in (units.ACTIVE_VOCABULARY, timezones.ACTIVE_VOCABULARY):
        if v.sources != ["default"]:
            print(f"vocabulary: {v.description}")


def activate(vocabulary) -> None:
    """Make ``inspector.units`` / ``inspector.timezones`` use ``vocabulary`` (in place; module names stay valid)."""
    if isinstance(vocabulary, UnitsVocabulary):
        from .. import units

        units.use_vocabulary(vocabulary)
    elif isinstance(vocabulary, TimezoneVocabulary):
        from .. import timezones

        timezones.use_vocabulary(vocabulary)
    else:
        raise TypeError(f"not a vocabulary: {type(vocabulary).__name__}")
