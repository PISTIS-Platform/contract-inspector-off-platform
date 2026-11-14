"""Time vocabulary: reference / alternative zone, epoch gate and name keywords."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ._common import VocabularyError, check_keys, check_mode, default_path, doc_mode, find_user_file, raise_if, read_toml


@dataclass
class TimezoneVocabulary:
    reference_tz: str
    alt_tz: str
    epoch_min: int
    epoch_max: int
    name_keywords: tuple[str, ...]
    origin: dict[str, str] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    description: str = "shipped default"


def _parse(doc: dict, where: str) -> dict:
    errors: list[str] = []
    check_keys(doc, {"mode", "reference_tz", "alt_tz", "epoch"}, where, errors)
    mode = doc_mode(doc, where, errors)
    ep = doc.get("epoch", {})
    if not isinstance(ep, dict):
        errors.append(f"{where}: [epoch] must be a table")
        ep = {}
    check_keys(ep, {"min", "max", "name_keywords", "extra_name_keywords"}, f"{where}: [epoch]", errors)
    for k in ("name_keywords", "extra_name_keywords"):
        v = ep.get(k)
        if v is not None and not (isinstance(v, list) and all(isinstance(x, str) and x for x in v)):
            errors.append(f"{where}: [epoch] {k} must be a list of non-empty strings")
    raise_if(errors, where)
    return {"mode": mode, "reference_tz": doc.get("reference_tz"), "alt_tz": doc.get("alt_tz"),
            "min": ep.get("min"), "max": ep.get("max"), "name_keywords": ep.get("name_keywords"),
            "extra": ep.get("extra_name_keywords") or []}


@lru_cache(maxsize=1)
def default_timezones() -> TimezoneVocabulary:
    path = default_path("timezones")
    p = _parse(read_toml(path), str(path))
    missing = [k for k in ("reference_tz", "alt_tz", "min", "max", "name_keywords") if p[k] is None]
    if missing:
        raise VocabularyError(f"{path}: the shipped default must define {', '.join(missing)}")
    kws = list(p["name_keywords"]) + [x for x in p["extra"] if x not in p["name_keywords"]]
    return TimezoneVocabulary(p["reference_tz"], p["alt_tz"], p["min"], p["max"], tuple(kws),
                              {k: "default" for k in ("reference_tz", "alt_tz", "epoch_min", "epoch_max", "name_keywords")},
                              ["default"], "shipped default (inspector/vocab/timezones.toml)")


def validate_timezones(v: TimezoneVocabulary, where: str = "time vocabulary") -> None:
    errors: list[str] = []
    for label, name in (("reference_tz", v.reference_tz), ("alt_tz", v.alt_tz)):
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            errors.append(f"{label}: {name!r} is not a known time-zone id")
    for label, x in (("epoch.min", v.epoch_min), ("epoch.max", v.epoch_max)):
        if isinstance(x, bool) or not isinstance(x, int):
            errors.append(f"{label} must be an integer, got {x!r}")
    if not errors and not v.epoch_min < v.epoch_max:
        errors.append(f"epoch.min ({v.epoch_min}) must be smaller than epoch.max ({v.epoch_max})")
    for k in v.name_keywords:
        if k != k.lower():
            errors.append(f"epoch.name_keywords: {k!r} must be lower-case")
    raise_if(errors, where)


def load_timezones(path=None, mode: str | None = None) -> TimezoneVocabulary:
    base = default_timezones()
    user_path, how = find_user_file("timezones", path)
    if user_path is None:
        return base
    where = str(user_path)
    p = _parse(read_toml(user_path), where)
    if mode is not None:
        p["mode"] = check_mode(mode)
    if p["mode"] == "replace":
        missing = [k for k in ("reference_tz", "alt_tz", "min", "max", "name_keywords") if p[k] is None]
        if missing:
            raise VocabularyError(f"{where}: replace mode is missing {', '.join(missing)}")
        cur = TimezoneVocabulary("", "", 0, 0, (), {}, [])
    else:
        cur = copy.deepcopy(base)
    org = dict(cur.origin) if p["mode"] == "extend" else {}
    for key, attr in (("reference_tz", "reference_tz"), ("alt_tz", "alt_tz"), ("min", "epoch_min"), ("max", "epoch_max")):
        if p[key] is not None:
            setattr(cur, attr, p[key])
            org[attr] = where
    if p["name_keywords"] is not None:
        cur.name_keywords = tuple(p["name_keywords"])
        org["name_keywords"] = where
    if p["extra"]:
        cur.name_keywords = cur.name_keywords + tuple(x for x in p["extra"] if x not in cur.name_keywords)
        org["name_keywords"] = where
    cur.origin = org
    cur.sources = (list(base.sources) if p["mode"] == "extend" else []) + [where]
    cur.description = f"{where} ({how}, {p['mode']} mode)" + (" over shipped default" if p["mode"] == "extend" else "")
    validate_timezones(cur, where)
    return cur
