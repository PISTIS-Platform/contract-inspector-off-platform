"""Unit vocabulary: parse, merge (extend / replace), validate."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from ._common import VocabularyError, check_keys, check_mode, default_path, doc_mode, find_user_file, raise_if, read_toml

_SUFFIX_RE = re.compile(r"^[a-z0-9]+$")
_ENTRY_KEYS = {"unit", "canonical", "dimension", "ambiguous", "alt"}


def make_registry():
    """A pint registry with the extra unit the vocabulary relies on (``var`` = reactive power, equal to watt)."""
    import pint

    ureg = pint.UnitRegistry()
    ureg.define("var = watt")
    return ureg


@dataclass
class UnitsVocabulary:
    suffix_map: dict[str, tuple[str, str, str]]
    alt_suffix: dict[str, str]
    ambiguous: set[str]
    dimension_keywords: dict[str, tuple[str, ...]]
    origin: dict[str, str] = field(default_factory=dict)
    keyword_origin: dict[str, str] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    description: str = "shipped default"
    warnings: list[str] = field(default_factory=list)


def _parse(doc: dict[str, Any], where: str) -> dict[str, Any]:
    errors: list[str] = []
    check_keys(doc, {"mode", "remove", "suffix", "dimension"}, where, errors)
    mode = doc_mode(doc, where, errors)
    remove = doc.get("remove", [])
    if not (isinstance(remove, list) and all(isinstance(x, str) for x in remove)):
        errors.append(f"{where}: remove must be a list of suffix names")
        remove = []
    entries: dict[str, dict[str, Any]] = {}
    for name, e in (doc.get("suffix") or {}).items():
        w = f"{where}: [suffix] {name}"
        if not isinstance(e, dict):
            errors.append(f"{w}: must be an inline table {{ unit = ..., canonical = ..., dimension = ... }}")
            continue
        check_keys(e, _ENTRY_KEYS, w, errors)
        for req in ("unit", "canonical", "dimension"):
            if not isinstance(e.get(req), str) or not e.get(req):
                errors.append(f"{w}: missing or empty string key {req!r}")
        if "ambiguous" in e and not isinstance(e["ambiguous"], bool):
            errors.append(f"{w}: ambiguous must be true or false")
        if "alt" in e and not isinstance(e["alt"], str):
            errors.append(f"{w}: alt must be a suffix name")
        entries[name] = {"unit": e.get("unit"), "canonical": e.get("canonical"), "dimension": e.get("dimension"),
                         "ambiguous": bool(e.get("ambiguous", False)), "alt": e.get("alt")}
    dims: dict[str, dict[str, Any]] = {}
    for name, d in (doc.get("dimension") or {}).items():
        w = f"{where}: [dimension.{name}]"
        if not isinstance(d, dict):
            errors.append(f"{w}: must be a table with keywords = [...]")
            continue
        check_keys(d, {"keywords", "extra_keywords"}, w, errors)
        for key in ("keywords", "extra_keywords"):
            v = d.get(key)
            if v is not None and not (isinstance(v, list) and all(isinstance(x, str) and x for x in v)):
                errors.append(f"{w}: {key} must be a list of non-empty strings")
        dims[name] = {"keywords": d.get("keywords"), "extra_keywords": d.get("extra_keywords") or []}
    raise_if(errors, where)
    return {"mode": mode, "remove": remove, "entries": entries, "dims": dims}


def _build(entries: dict[str, dict], kw: dict[str, list[str]], origin: dict, kw_origin: dict, sources: list[str],
           description: str = "") -> UnitsVocabulary:
    return UnitsVocabulary(
        suffix_map={s: (e["unit"], e["canonical"], e["dimension"]) for s, e in entries.items()},
        alt_suffix={s: e["alt"] for s, e in entries.items() if e.get("alt")},
        ambiguous={s for s, e in entries.items() if e["ambiguous"]},
        dimension_keywords={d: tuple(v) for d, v in kw.items() if v},
        origin=dict(origin), keyword_origin=dict(kw_origin), sources=list(sources), description=description)


def _from_parsed(p: dict, origin_label: str, description: str) -> UnitsVocabulary:
    kw = {d: list(v["keywords"] or []) + v["extra_keywords"] for d, v in p["dims"].items()}
    return _build(p["entries"], kw, {s: origin_label for s in p["entries"]}, {d: origin_label for d in kw},
                  [origin_label], description)


@lru_cache(maxsize=1)
def default_units() -> UnitsVocabulary:
    """The shipped vocabulary (``inspector/vocab/units.toml``), not validated here (the test-suite does)."""
    path = default_path("units")
    p = _parse(read_toml(path), str(path))
    return _from_parsed(p, "default", "shipped default (inspector/vocab/units.toml)")


def _merge(base: UnitsVocabulary, user: dict, user_label: str) -> UnitsVocabulary:
    mode = user["mode"]
    entries: dict[str, dict] = {}
    origin: dict[str, str] = {}
    kw: dict[str, list[str]] = {}
    kw_origin: dict[str, str] = {}
    if mode == "extend":
        for s, (u, c, d) in base.suffix_map.items():
            entries[s] = {"unit": u, "canonical": c, "dimension": d, "ambiguous": s in base.ambiguous,
                          "alt": base.alt_suffix.get(s)}
            origin[s] = base.origin.get(s, "default")
        kw = {d: list(v) for d, v in base.dimension_keywords.items()}
        kw_origin = dict(base.keyword_origin)
    elif user["remove"]:
        raise VocabularyError(f"{user_label}: 'remove' is only valid in extend mode")
    unknown = [s for s in user["remove"] if s not in entries]
    if unknown:
        raise VocabularyError(f"{user_label}: cannot remove unknown suffix(es): {', '.join(unknown)}")
    for s in user["remove"]:
        entries.pop(s)
        origin.pop(s, None)
    for s, e in user["entries"].items():
        entries[s] = e
        origin[s] = user_label
    for d, v in user["dims"].items():
        if v["keywords"] is not None:
            kw[d] = list(v["keywords"])
        kw.setdefault(d, [])
        for x in v["extra_keywords"]:
            if x not in kw[d]:
                kw[d].append(x)
        kw_origin[d] = user_label
    sources = (list(base.sources) if mode == "extend" else []) + [user_label]
    return _build(entries, kw, origin, kw_origin, sources)


def validate_units(v: UnitsVocabulary, registry=None, where: str = "units vocabulary") -> list[str]:
    """Validate; raise VocabularyError with all errors, return warnings."""
    ureg = registry if registry is not None else make_registry()
    errors: list[str] = []
    warnings: list[str] = []
    for s, (unit, canon, dim) in v.suffix_map.items():
        if not _SUFFIX_RE.match(s):
            errors.append(f"suffix {s!r}: must be lower-case letters/digits only, no underscore")
        ok = True
        for label, u in (("unit", unit), ("canonical", canon)):
            try:
                ureg.Quantity(1.0, u)
            except Exception as e:
                errors.append(f"suffix {s!r}: pint does not know {label} {u!r} ({type(e).__name__})")
                ok = False
        if ok:
            try:
                ureg.Quantity(1.0, unit).to(canon)
            except Exception:
                errors.append(f"suffix {s!r}: unit {unit!r} cannot be converted to canonical unit {canon!r}")
    by_dim: dict[str, set[str]] = {}
    for s, (_u, canon, dim) in v.suffix_map.items():
        by_dim.setdefault(dim, set()).add(canon)
    for dim, canons in by_dim.items():
        if len(canons) > 1:
            errors.append(f"dimension {dim!r}: suffixes disagree on the canonical unit {sorted(canons)}")
    seen: dict[str, str] = {}
    for s, (unit, _c, _d) in v.suffix_map.items():
        if unit in seen:
            errors.append(f"suffixes {seen[unit]!r} and {s!r} use the same unit {unit!r}")
        seen.setdefault(unit, s)
    for s, a in v.alt_suffix.items():
        if s not in v.suffix_map:
            errors.append(f"alt: suffix {s!r} is not defined")
        elif a not in v.suffix_map:
            errors.append(f"suffix {s!r}: alt {a!r} is not a defined suffix")
        elif v.suffix_map[a][2] != v.suffix_map[s][2]:
            errors.append(f"suffix {s!r}: alt {a!r} is in dimension {v.suffix_map[a][2]!r}, not {v.suffix_map[s][2]!r}")
        elif a == s:
            errors.append(f"suffix {s!r}: alt must differ from the suffix itself")
    for s in sorted(v.ambiguous):
        dim = v.suffix_map[s][2]
        if not v.dimension_keywords.get(dim):
            errors.append(f"suffix {s!r} is ambiguous but dimension {dim!r} has no keywords")
    for d, kws in v.dimension_keywords.items():
        for k in kws:
            if k != k.lower():
                errors.append(f"dimension {d!r}: keyword {k!r} must be lower-case")
        if d not in by_dim:
            warnings.append(f"dimension {d!r} has keywords but no suffix uses it")
    sources = set(seen)
    for dim, canons in by_dim.items():
        if all(v.origin.get(s, "default") == "default" for s, (_u, _c, d) in v.suffix_map.items() if d == dim):
            continue
        for c in canons:
            if c not in sources:
                warnings.append(f"canonical unit {c!r} of {dim!r} is not the unit of any suffix, so a declared {c!r} is not recognised")
    raise_if(errors, where)
    return warnings


def load_units(path=None, mode: str | None = None, registry=None) -> UnitsVocabulary:
    """Load the unit vocabulary: explicit path, environment, data folder or shipped default."""
    base = default_units()
    user_path, how = find_user_file("units", path)
    if user_path is None:
        return base
    where = str(user_path)
    p = _parse(read_toml(user_path), where)
    if mode is not None:
        p["mode"] = check_mode(mode)
    v = _merge(base, p, where)
    v.description = f"{where} ({how}, {p['mode']} mode)" + (" over shipped default" if p["mode"] == "extend" else "")
    v.warnings = validate_units(v, registry, where)
    return v
