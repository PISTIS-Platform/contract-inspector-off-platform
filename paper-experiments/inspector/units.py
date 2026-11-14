"""Measurement-unit detection and canonical normalization."""

from __future__ import annotations

from math import floor, log10
from typing import Any

import pint

from . import vocab as _vocab
from .loader import Dataset

_UREG = pint.UnitRegistry()
_UREG.define("var = watt")  # pint has no reactive-power unit

# Filled from inspector/vocab/units.toml by use_vocabulary().
SUFFIX_MAP: dict[str, tuple[str, str, str]] = {}
ALT_SUFFIX: dict[str, str] = {}
_AMBIGUOUS_SUFFIXES: set[str] = set()
_DIMENSION_KEYWORDS: dict[str, tuple[str, ...]] = {}
_UNIT_TO_CANONICAL: dict[str, str] = {}
ACTIVE_VOCABULARY = None

_CANONICAL_SIG_FIGS = 6


def _round_sig(x: float, sig: int = _CANONICAL_SIG_FIGS) -> float:
    # values reached through different conversion paths must agree to the last bit
    if x == 0 or not _finite(x):
        return 0.0
    return round(x, sig - int(floor(log10(abs(x)))) - 1)


def _finite(x: float) -> bool:
    return x == x and x not in (float("inf"), float("-inf"))


def _as_number(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            f = float(s)
        except ValueError:
            return None
    else:
        return None
    return f if _finite(f) else None


def use_vocabulary(vocabulary) -> None:
    """Install ``vocabulary``; the module dicts are updated in place."""
    SUFFIX_MAP.clear()
    SUFFIX_MAP.update(vocabulary.suffix_map)
    ALT_SUFFIX.clear()
    ALT_SUFFIX.update(vocabulary.alt_suffix)
    _AMBIGUOUS_SUFFIXES.clear()
    _AMBIGUOUS_SUFFIXES.update(vocabulary.ambiguous)
    _DIMENSION_KEYWORDS.clear()
    _DIMENSION_KEYWORDS.update(vocabulary.dimension_keywords)
    _UNIT_TO_CANONICAL.clear()
    _UNIT_TO_CANONICAL.update({src: canon for src, canon, _dim in SUFFIX_MAP.values()})
    global ACTIVE_VOCABULARY
    ACTIVE_VOCABULARY = vocabulary


use_vocabulary(_vocab.active_units(_UREG))


def split_suffix(field: str) -> tuple[str, str | None]:
    """Split a field name into (base, unit-suffix) if the suffix is known."""
    if "_" not in field:
        return field, None
    base, suffix = field.rsplit("_", 1)
    if suffix not in SUFFIX_MAP or not base:
        return field, None
    if suffix in _AMBIGUOUS_SUFFIXES:
        dimension = SUFFIX_MAP[suffix][2]
        keywords = _DIMENSION_KEYWORDS.get(dimension, ())
        if not any(kw in base.lower() for kw in keywords):
            return field, None
    return base, suffix


def explain_field(field: str) -> dict:
    """Why a field name is, or is not, read as unit-bearing."""
    if "_" not in field:
        return {"detected": False, "reason": "no '_' in the name, so there is no suffix to read"}
    base, suffix = field.rsplit("_", 1)
    if not base:
        return {"detected": False, "reason": "nothing before the suffix"}
    if suffix not in SUFFIX_MAP:
        return {"detected": False, "reason": f"suffix {suffix!r} is not in the unit vocabulary"}
    unit, canon, dim = SUFFIX_MAP[suffix]
    info = {"base": base, "suffix": suffix, "unit": unit, "canonical": canon, "dimension": dim}
    if suffix in _AMBIGUOUS_SUFFIXES:
        kws = _DIMENSION_KEYWORDS.get(dim, ())
        hit = next((kw for kw in kws if kw in base.lower()), None)
        if hit is None:
            shown = f"none of the {dim} keywords {list(kws)}" if kws else f"no {dim} keywords are defined"
            return {"detected": False, **info,
                    "reason": f"suffix {suffix!r} ({dim}) is ambiguous and {base!r} contains {shown}"}
        return {"detected": True, **info,
                "reason": f"suffix {suffix!r} is ambiguous; accepted because {base!r} contains the {dim} keyword {hit!r}"}
    return {"detected": True, **info, "reason": f"suffix {suffix!r} ({dim}, unambiguous)"}


def _convert(value: float, from_unit: str, to_unit: str) -> float:
    return float(_UREG.Quantity(value, from_unit).to(to_unit).magnitude)


def to_canonical(field: str, value: Any, declared_unit: str | None = None) -> tuple[str, float] | None:
    """Return (canonical_field, canonical_value) for a unit-bearing field."""
    num = _as_number(value)
    if num is None:
        return None
    base, suffix = split_suffix(field)
    if declared_unit is not None:
        canon_unit = _UNIT_TO_CANONICAL.get(declared_unit)
        if canon_unit is None:
            return None
        return base, _round_sig(_convert(num, declared_unit, canon_unit))
    if suffix is None:
        return None
    src_unit, canon_unit, _ = SUFFIX_MAP[suffix]
    return base, _round_sig(_convert(num, src_unit, canon_unit))


def to_alternative(field: str, value: Any) -> tuple[str, float] | None:
    """Re-express a field in a sibling unit (the T8a attack)."""
    base, suffix = split_suffix(field)
    num = _as_number(value)
    if suffix is None or num is None:
        return None
    alt_suffix = ALT_SUFFIX.get(suffix)
    if alt_suffix is None:
        return None
    src_unit = SUFFIX_MAP[suffix][0]
    alt_unit = SUFFIX_MAP[alt_suffix][0]
    converted = _convert(num, src_unit, alt_unit)
    alt_value = str(converted) if isinstance(value, str) else converted
    return f"{base}_{alt_suffix}", alt_value


def _normalize_record(rec: dict, unit_meta: dict[str, str] | None = None) -> dict:
    out: dict = {}
    for k, v in rec.items():
        declared = unit_meta.get(k) if unit_meta and isinstance(k, str) else None
        canon = to_canonical(k, v, declared) if isinstance(k, str) else None
        # a canonical name that clashes with another field keeps the original key
        if canon is not None and canon[0] not in out and canon[0] not in rec:
            out[canon[0]] = canon[1]
        else:
            out[k] = v
    return out


def normalize_dataset(ds: Dataset) -> Dataset:
    if not ds.is_structured or not isinstance(ds.data, list):
        return ds
    unit_meta = getattr(ds, "unit_meta", None)
    new_data = [
        _normalize_record(r, unit_meta) if isinstance(r, dict) else r
        for r in ds.data
    ]
    return Dataset(data=new_data, modality=ds.modality,
                   source_path=ds.source_path + ".unitnorm")


def count_unit_bearing_fields(ds: Dataset) -> int:
    """Number of distinct unit-bearing field names."""
    if not ds.is_structured or not isinstance(ds.data, list):
        return 0
    seen = set()
    for r in ds.data:
        if isinstance(r, dict):
            for k in r:
                if isinstance(k, str) and split_suffix(k)[1] is not None:
                    seen.add(k)
    return len(seen)
