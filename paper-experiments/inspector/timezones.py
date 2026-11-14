"""Timezone detection and UTC canonicalization (companion to ``units.py``)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from . import vocab as _vocab
from .loader import Dataset

# Filled from inspector/vocab/timezones.toml by use_vocabulary().
REFERENCE_TZ: ZoneInfo = None
ALT_TZ: ZoneInfo = None

# date-time with a time of day; an offset is optional
_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")

_EPOCH_MIN: int = 0
_EPOCH_MAX: int = 0

_EPOCH_NAME_KEYWORDS: frozenset = frozenset()


def use_vocabulary(vocabulary) -> None:
    """Install ``vocabulary``; the constants are rebound."""
    global REFERENCE_TZ, ALT_TZ, _EPOCH_MIN, _EPOCH_MAX, _EPOCH_NAME_KEYWORDS, ACTIVE_VOCABULARY
    REFERENCE_TZ = ZoneInfo(vocabulary.reference_tz)
    ALT_TZ = ZoneInfo(vocabulary.alt_tz)
    _EPOCH_MIN = int(vocabulary.epoch_min)
    _EPOCH_MAX = int(vocabulary.epoch_max)
    _EPOCH_NAME_KEYWORDS = frozenset(vocabulary.name_keywords)
    ACTIVE_VOCABULARY = vocabulary


ACTIVE_VOCABULARY = None
use_vocabulary(_vocab.active_timezones())


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not _DT_RE.match(s):
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _is_epoch_int(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return _EPOCH_MIN <= value <= _EPOCH_MAX
    if isinstance(value, float):
        if value != int(value):
            return False
        return _EPOCH_MIN <= int(value) <= _EPOCH_MAX
    if isinstance(value, str):
        s = value.strip()
        try:
            i = int(s)
            return _EPOCH_MIN <= i <= _EPOCH_MAX
        except ValueError:
            return False
    return False


def _column_is_epoch(field_name: str, values: list[Any]) -> bool:
    # an integer column inside the epoch range is a timestamp column whatever its name says;
    # the name keywords of the vocabulary are only reported by `python -m inspector.vocab scan`
    non_null = [v for v in values if v is not None and v != "" and v == v]
    return bool(non_null) and all(_is_epoch_int(v) for v in non_null)


def explain_column(field_name: str, values: list[Any]) -> dict:
    """Why a column is, or is not, read as timestamps."""
    non_null = [v for v in values if v is not None and v != "" and v == v]
    if not non_null:
        return {"kind": None, "reason": "no non-empty values"}
    parsed = [(_parse_dt(v) if isinstance(v, str) else None) for v in non_null]
    n_iso = sum(1 for d in parsed if d is not None)
    if n_iso:
        n_off = sum(1 for d in parsed if d is not None and d.tzinfo is not None)
        zone = (f"{n_off} of {n_iso} carry an offset; the others are read as {REFERENCE_TZ.key}" if n_off < n_iso
                else "all carry an offset")
        return {"kind": "iso", "reason": f"ISO-8601 date-time in {n_iso} of {len(non_null)} values ({zone})"}
    if not all(_is_epoch_int(v) for v in non_null):
        bad = next(v for v in non_null if not _is_epoch_int(v))
        return {"kind": None, "reason": f"values are neither ISO date-times nor integers in the epoch range "
                                        f"(e.g. {str(bad)[:24]!r})"}
    hit = next((kw for kw in sorted(_EPOCH_NAME_KEYWORDS) if kw in field_name.lower()), None)
    if hit is not None:
        return {"kind": "epoch", "reason": f"every value is an integer in the epoch range; name contains the keyword {hit!r}"}
    return {"kind": "epoch", "reason": "every value is an integer in the epoch range; no name keyword matched "
                                       "(the range alone is enough for the gate)"}


def epoch_to_utc(value: Any) -> str | None:
    """Convert a Unix-epoch integer to a UTC ISO string."""
    if not _is_epoch_int(value):
        return None
    if isinstance(value, (int, float)):
        epoch = int(value)
    else:
        try:
            epoch = int(str(value).strip())
        except ValueError:
            return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def to_alternative_tz(value: Any) -> str | None:
    """Re-express a timestamp in the alternative timezone (the T9 attack)."""
    dt = _parse_dt(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=REFERENCE_TZ)
    return dt.astimezone(ALT_TZ).isoformat()


def to_epoch(value: Any) -> int | None:
    """Convert an ISO timestamp to Unix epoch seconds (the T8b attack)."""
    dt = _parse_dt(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=REFERENCE_TZ)
    return int(dt.astimezone(timezone.utc).timestamp())


def to_utc(value: Any) -> str | None:
    """Canonicalise a timestamp to UTC ISO string (the defence for ISO inputs)."""
    dt = _parse_dt(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=REFERENCE_TZ)
    return dt.astimezone(timezone.utc).isoformat()


def _transform_record(rec: dict, fn) -> dict:
    out: dict = {}
    for k, v in rec.items():
        nv = fn(v) if isinstance(v, str) else None
        out[k] = nv if nv is not None else v
    return out


def _transform_record_with_epoch(rec: dict, epoch_fields: set[str]) -> dict:
    out: dict = {}
    for k, v in rec.items():
        if k in epoch_fields:
            nv = epoch_to_utc(v)
            out[k] = nv if nv is not None else v
        else:
            nv = to_utc(v) if isinstance(v, str) else None
            out[k] = nv if nv is not None else v
    return out


def convert_timezones_dataset(ds: Dataset) -> Dataset:
    if not ds.is_structured or not isinstance(ds.data, list):
        return ds
    data = [_transform_record(r, to_alternative_tz) if isinstance(r, dict) else r
            for r in ds.data]
    return Dataset(data=data, modality=ds.modality,
                   source_path=ds.source_path + ".T9_timezone")


def convert_timestamps_to_epoch(ds: Dataset) -> Dataset:
    if not ds.is_structured or not isinstance(ds.data, list):
        return ds

    def _to_epoch_rec(rec: dict) -> dict:
        out: dict = {}
        for k, v in rec.items():
            ep = to_epoch(v) if isinstance(v, str) else None
            out[k] = ep if ep is not None else v
        return out

    data = [_to_epoch_rec(r) if isinstance(r, dict) else r for r in ds.data]
    return Dataset(data=data, modality=ds.modality,
                   source_path=ds.source_path + ".T8b_epoch")


def normalize_timezones_dataset(ds: Dataset) -> Dataset:
    """Canonicalise every timestamp, ISO or epoch, to UTC."""
    if not ds.is_structured or not isinstance(ds.data, list):
        return ds

    field_values: dict[str, list[Any]] = {}
    for rec in ds.data:
        if isinstance(rec, dict):
            for k, v in rec.items():
                field_values.setdefault(k, []).append(v)

    epoch_fields: set[str] = {
        k for k, vals in field_values.items()
        if _column_is_epoch(k, vals)
    }

    if epoch_fields:
        data = [_transform_record_with_epoch(r, epoch_fields)
                if isinstance(r, dict) else r
                for r in ds.data]
    else:
        data = [_transform_record(r, to_utc) if isinstance(r, dict) else r
                for r in ds.data]

    return Dataset(data=data, modality=ds.modality,
                   source_path=ds.source_path + ".tznorm")


def count_timezone_bearing_fields(ds: Dataset) -> int:
    if not ds.is_structured or not isinstance(ds.data, list):
        return 0
    seen_iso: set[str] = set()
    field_values: dict[str, list[Any]] = {}
    for r in ds.data:
        if isinstance(r, dict):
            for k, v in r.items():
                if isinstance(v, str) and _parse_dt(v) is not None:
                    seen_iso.add(k)
                field_values.setdefault(k, []).append(v)

    seen_epoch: set[str] = {
        k for k, vals in field_values.items()
        if k not in seen_iso and _column_is_epoch(k, vals)
    }
    return len(seen_iso | seen_epoch)
