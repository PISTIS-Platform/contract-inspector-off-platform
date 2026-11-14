"""Dataset augmentation for evaluation."""

import copy
import json
import random
import string
from typing import Any

from .loader import Dataset, Modality, load_from_string


class DatasetAugmenter:
    """Applies the threat modifications T1-T9 to datasets."""

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    def exact_copy(self, dataset: Dataset) -> Dataset:
        """Return an identical copy (T1)."""
        data = copy.deepcopy(dataset.data)
        return Dataset(data=data, modality=dataset.modality,
                       source_path=dataset.source_path + ".T1_copy")

    def reorder_fields(self, dataset: Dataset) -> Dataset:
        """Reorder dictionary keys / CSV columns (T2)."""
        data = copy.deepcopy(dataset.data)
        data = self._reorder(data)
        return Dataset(data=data, modality=dataset.modality,
                       source_path=dataset.source_path + ".T2_reorder")

    def _reorder(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            items = list(obj.items())
            self.rng.shuffle(items)
            return {k: self._reorder(v) for k, v in items}
        elif isinstance(obj, list):
            return [self._reorder(item) for item in obj]
        return obj

    def rename_fields(self, dataset: Dataset, fraction: float = 0.3) -> Dataset:
        """Rename a fraction of field names (T3)."""
        data = copy.deepcopy(dataset.data)
        data = self._rename_keys(data, fraction)
        return Dataset(data=data, modality=dataset.modality,
                       source_path=dataset.source_path + ".T3_rename")

    def _rename_keys(self, obj: Any, fraction: float) -> Any:
        if isinstance(obj, dict):
            new_dict = {}
            for k, v in obj.items():
                if self.rng.random() < fraction:
                    new_key = k + "_" + self._random_suffix(3)
                else:
                    new_key = k
                new_dict[new_key] = self._rename_keys(v, fraction)
            return new_dict
        elif isinstance(obj, list):
            return [self._rename_keys(item, fraction) for item in obj]
        return obj

    def add_spurious_fields(self, dataset: Dataset, num_fields: int = 3) -> Dataset:
        """Add random spurious fields to the dataset (T3)."""
        data = copy.deepcopy(dataset.data)
        data = self._add_fields(data, num_fields)
        return Dataset(data=data, modality=dataset.modality,
                       source_path=dataset.source_path + ".T3_spurious")

    def _add_fields(self, obj: Any, num_fields: int) -> Any:
        if isinstance(obj, dict):
            for _ in range(num_fields):
                key = "extra_" + self._random_suffix(5)
                obj[key] = self._random_value()
            for k, v in obj.items():
                obj[k] = self._add_fields(v, max(1, num_fields // 2))
            return obj
        elif isinstance(obj, list):
            return [self._add_fields(item, num_fields) for item in obj]
        return obj

    def perturb_values(self, dataset: Dataset, fraction: float = 0.3,
                       noise_scale: float = 0.05) -> Dataset:
        """Perturb numeric values and modify text fields (T4)."""
        data = copy.deepcopy(dataset.data)
        data = self._perturb(data, fraction, noise_scale)
        return Dataset(data=data, modality=dataset.modality,
                       source_path=dataset.source_path + ".T4_perturb")

    def _perturb(self, obj: Any, fraction: float, noise_scale: float) -> Any:
        if isinstance(obj, dict):
            return {k: self._perturb(v, fraction, noise_scale) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._perturb(item, fraction, noise_scale) for item in obj]
        elif isinstance(obj, (int, float)) and self.rng.random() < fraction:
            noise = obj * noise_scale * self.rng.gauss(0, 1)
            if isinstance(obj, int):
                return int(round(obj + noise))
            return round(obj + noise, 6)
        elif isinstance(obj, str) and len(obj) > 3 and self.rng.random() < fraction:
            return self._perturb_string(obj)
        return obj

    def _perturb_string(self, s: str) -> str:
        chars = list(s)
        num_changes = max(1, len(chars) // 10)
        for _ in range(num_changes):
            idx = self.rng.randint(0, len(chars) - 1)
            op = self.rng.choice(["substitute", "delete", "insert"])
            if op == "substitute":
                chars[idx] = self.rng.choice(string.ascii_lowercase)
            elif op == "delete" and len(chars) > 1:
                chars.pop(idx)
            elif op == "insert":
                chars.insert(idx, self.rng.choice(string.ascii_lowercase))
        return "".join(chars)

    def extract_subset(self, dataset: Dataset, fraction: float = 0.5) -> Dataset:
        """Extract a random subset of records (T5)."""
        data = copy.deepcopy(dataset.data)
        if isinstance(data, list):
            k = max(1, int(len(data) * fraction))
            data = self.rng.sample(data, k)
        elif isinstance(data, dict):
            keys = list(data.keys())
            k = max(1, int(len(keys) * fraction))
            selected = self.rng.sample(keys, k)
            data = {key: data[key] for key in selected}
        return Dataset(data=data, modality=dataset.modality,
                       source_path=dataset.source_path + ".T5_subset")

    def synonym_replace(self, dataset: Dataset, fraction: float = 0.2) -> Dataset:
        """Replace string values with simple synonyms/paraphrases (T6)."""
        synonyms = {
            "name": "identifier", "id": "code", "address": "location",
            "city": "municipality", "country": "nation", "type": "category",
            "status": "state", "description": "details", "price": "cost",
            "value": "amount", "date": "timestamp", "start": "begin",
            "end": "finish", "active": "enabled", "true": "yes",
            "false": "no", "error": "fault", "warning": "alert",
            "temperature": "temp", "speed": "velocity", "power": "energy",
        }
        data = copy.deepcopy(dataset.data)
        data = self._apply_synonyms(data, synonyms, fraction)
        return Dataset(data=data, modality=dataset.modality,
                       source_path=dataset.source_path + ".T6_synonym")

    def _apply_synonyms(self, obj: Any, synonyms: dict, fraction: float) -> Any:
        if isinstance(obj, dict):
            new_dict = {}
            for k, v in obj.items():
                new_key = k
                k_lower = k.lower()
                if k_lower in synonyms and self.rng.random() < fraction:
                    new_key = synonyms[k_lower]
                new_dict[new_key] = self._apply_synonyms(v, synonyms, fraction)
            return new_dict
        elif isinstance(obj, list):
            return [self._apply_synonyms(item, synonyms, fraction) for item in obj]
        elif isinstance(obj, str):
            words = obj.split()
            new_words = []
            for w in words:
                w_lower = w.lower()
                if w_lower in synonyms and self.rng.random() < fraction:
                    new_words.append(synonyms[w_lower])
                else:
                    new_words.append(w)
            return " ".join(new_words)
        return obj

    def composite_attack(self, dataset: Dataset) -> Dataset:
        """Apply a combination of T3 + T4 + T5 modifications (T7)."""
        d = self.extract_subset(dataset, fraction=0.7)
        d = self.rename_fields(d, fraction=0.2)
        d = self.perturb_values(d, fraction=0.3, noise_scale=0.03)
        d.source_path = dataset.source_path + ".T7_composite"
        return d

    def convert_units(self, dataset: Dataset, fraction: float = 1.0) -> Dataset:
        """Rewrite unit-bearing fields into alternative units (T8)."""
        data = copy.deepcopy(dataset.data)
        data = self._convert_units(data, fraction)
        return Dataset(data=data, modality=dataset.modality,
                       source_path=dataset.source_path + ".T8_units")

    def convert_units_value_only(self, dataset: Dataset, fraction: float = 1.0,
                                  unit_targets: dict[str, str] | None = None) -> Dataset:
        """Value-only T8a: convert values to another unit, keep the field names, update ``unit_meta``."""
        from .units import ALT_SUFFIX, SUFFIX_MAP, _as_number, _convert, split_suffix

        unit_targets = unit_targets or {}
        base_meta = dict(getattr(dataset, "unit_meta", None) or {})
        new_meta = dict(base_meta)

        def _convert_record(rec: dict) -> dict:
            out: dict = {}
            for k, v in rec.items():
                declared = base_meta.get(k) if isinstance(k, str) else None
                suffix = None
                if declared is None and isinstance(k, str):
                    _base, suffix = split_suffix(k)
                    declared = SUFFIX_MAP[suffix][0] if suffix else None
                if declared is not None and self.rng.random() < fraction:
                    if k in unit_targets:
                        alt_unit = unit_targets[k]
                    else:
                        suf_match = suffix or next(
                            (s for s, (src, _, _) in SUFFIX_MAP.items() if src == declared), None)
                        alt_suf = ALT_SUFFIX.get(suf_match) if suf_match else None
                        alt_unit = SUFFIX_MAP[alt_suf][0] if alt_suf else None
                    if alt_unit is not None:
                        num = _as_number(v)
                        if num is not None:
                            converted = _convert(num, declared, alt_unit)
                            out[k] = str(converted) if isinstance(v, str) else converted
                            new_meta[k] = alt_unit
                            continue
                out[k] = v
            return out

        data = copy.deepcopy(dataset.data)
        if isinstance(data, list):
            data = [_convert_record(r) if isinstance(r, dict) else r for r in data]
        result = Dataset(data=data, modality=dataset.modality,
                         source_path=dataset.source_path + ".T8_value_only",
                         unit_meta=new_meta)
        return result

    def convert_units_named_targets(self, dataset: Dataset,
                                    target_suffixes: dict[str, str]) -> Dataset:
        """Name-encoded T8a with an explicit per-field target unit."""
        from .units import SUFFIX_MAP, _as_number, _convert, split_suffix

        plan: dict[str, tuple[str, str, str]] = {}
        for field_name, tgt in target_suffixes.items():
            base, suffix = split_suffix(field_name)
            if suffix is None:
                raise ValueError(f"{field_name!r} carries no recognised unit suffix")
            plan[field_name] = (f"{base}_{tgt}", SUFFIX_MAP[suffix][0], SUFFIX_MAP[tgt][0])

        def _convert_record(rec: dict) -> dict:
            out: dict = {}
            for k, v in rec.items():
                if k in plan:
                    new_name, src_unit, dst_unit = plan[k]
                    num = _as_number(v)
                    if num is not None:
                        conv = _convert(num, src_unit, dst_unit)
                        out[new_name] = str(conv) if isinstance(v, str) else conv
                    else:
                        out[new_name] = v
                else:
                    out[k] = v
            return out

        data = copy.deepcopy(dataset.data)
        if isinstance(data, list):
            data = [_convert_record(r) if isinstance(r, dict) else r for r in data]
        return Dataset(data=data, modality=dataset.modality,
                       source_path=dataset.source_path + ".T8_named_targets")

    def convert_units_and_epoch_named_targets(self, dataset: Dataset,
                                              target_suffixes: dict[str, str]) -> Dataset:
        """Name-encoded T8a (explicit targets) + T8b epoch encoding."""
        d = self.convert_units_named_targets(dataset, target_suffixes)
        from .timezones import convert_timestamps_to_epoch
        d2 = copy.copy(convert_timestamps_to_epoch(d))
        d2.source_path = dataset.source_path + ".T8_stressed_named"
        return d2

    def convert_units_and_epoch(self, dataset: Dataset) -> Dataset:
        """Apply T8a (unit conversion) and T8b (epoch encoding) concurrently."""
        d = self.convert_units(dataset)
        from .timezones import convert_timestamps_to_epoch
        d2 = convert_timestamps_to_epoch(d)
        d2 = copy.copy(d2)
        d2.source_path = dataset.source_path + ".T8_stressed"
        return d2

    def convert_units_and_epoch_value_only(self, dataset: Dataset,
                                           unit_targets: dict[str, str] | None = None) -> Dataset:
        """Value-only counterpart of ``convert_units_and_epoch``."""
        d = self.convert_units_value_only(dataset, unit_targets=unit_targets)
        from .timezones import convert_timestamps_to_epoch
        d2 = convert_timestamps_to_epoch(d)
        d2 = copy.copy(d2)
        d2.unit_meta = dict(d.unit_meta)
        d2.source_path = dataset.source_path + ".T8_stressed_value_only"
        return d2

    def convert_timezone(self, dataset: Dataset) -> Dataset:
        """Re-express every timezone-bearing timestamp in another timezone (T9)."""
        from .timezones import convert_timezones_dataset
        return convert_timezones_dataset(dataset)

    def _convert_units(self, obj: Any, fraction: float) -> Any:
        from .units import to_alternative
        if isinstance(obj, dict):
            out: dict = {}
            for k, v in obj.items():
                alt = (to_alternative(k, v)
                       if isinstance(k, str) and self.rng.random() < fraction
                       else None)
                if alt is not None:
                    out[alt[0]] = alt[1]
                else:
                    out[k] = self._convert_units(v, fraction)
            return out
        elif isinstance(obj, list):
            return [self._convert_units(item, fraction) for item in obj]
        return obj

    def _random_suffix(self, length: int) -> str:
        return "".join(self.rng.choices(string.ascii_lowercase, k=length))

    def _random_value(self) -> Any:
        choice = self.rng.choice(["int", "float", "str"])
        if choice == "int":
            return self.rng.randint(0, 1000)
        elif choice == "float":
            return round(self.rng.uniform(0, 100), 2)
        else:
            return self._random_suffix(8)


def generate_dissimilar_dataset(modality: Modality, size: int = 10,
                                seed: int = 0) -> Dataset:
    """Generate a random dataset that is unrelated to any existing dataset."""
    rng = random.Random(seed)

    if modality == Modality.STRUCTURED_JSON:
        data = []
        for i in range(size):
            record = {
                "id": rng.randint(10000, 99999),
                "field_a": "".join(rng.choices(string.ascii_letters, k=10)),
                "field_b": round(rng.uniform(0, 1000), 2),
                "field_c": rng.choice(["alpha", "beta", "gamma", "delta"]),
            }
            data.append(record)
        content = json.dumps(data, indent=2)
        return load_from_string(content, modality, f"<random_{seed}>")

    elif modality == Modality.STRUCTURED_CSV:
        lines = ["col_x,col_y,col_z"]
        for i in range(size):
            lines.append(
                f"{rng.randint(0,999)},"
                f"{''.join(rng.choices(string.ascii_lowercase, k=6))},"
                f"{round(rng.uniform(0, 500), 1)}"
            )
        content = "\n".join(lines)
        return load_from_string(content, modality, f"<random_{seed}>")

    else:
        words = ["".join(rng.choices(string.ascii_lowercase, k=rng.randint(3, 10)))
                 for _ in range(size * 10)]
        content = " ".join(words)
        return load_from_string(content, Modality.UNSTRUCTURED_TEXT, f"<random_{seed}>")
