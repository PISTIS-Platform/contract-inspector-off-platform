"""Pre-processing module: path-value extraction and normalization."""

import xml.etree.ElementTree as ET
from typing import Any

from .loader import Dataset, Modality


def flatten_json(data: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten a JSON object/array into a list of (path, value) pairs."""
    pairs = []

    if isinstance(data, dict):
        for key, value in data.items():
            full_path = f"{prefix}.{key}" if prefix else key
            pairs.extend(flatten_json(value, full_path))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            full_path = f"{prefix}[{i}]"
            pairs.extend(flatten_json(item, full_path))
    else:
        pairs.append((prefix, _normalize_value(data)))

    return pairs


def flatten_csv(rows: list[dict]) -> list[tuple[str, str]]:
    """Flatten CSV rows into (path, value) pairs."""
    pairs = []
    for i, row in enumerate(rows):
        for col, value in row.items():
            path = f"row[{i}].{col}"
            pairs.append((path, _normalize_value(value)))
    return pairs


def flatten_xml(element: ET.Element, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten an XML element tree into (path, value) pairs."""
    pairs = []
    tag = element.tag
    if "}" in tag:
        tag = tag.split("}", 1)[1]

    current_path = f"{prefix}.{tag}" if prefix else tag

    if element.text and element.text.strip():
        pairs.append((current_path, _normalize_value(element.text.strip())))

    for attr_name, attr_value in element.attrib.items():
        pairs.append((f"{current_path}@{attr_name}", _normalize_value(attr_value)))

    child_counts: dict[str, int] = {}
    for child in element:
        child_tag = child.tag
        if "}" in child_tag:
            child_tag = child_tag.split("}", 1)[1]
        idx = child_counts.get(child_tag, 0)
        child_counts[child_tag] = idx + 1

    child_indices: dict[str, int] = {}
    for child in element:
        child_tag = child.tag
        if "}" in child_tag:
            child_tag = child_tag.split("}", 1)[1]

        idx = child_indices.get(child_tag, 0)
        child_indices[child_tag] = idx + 1

        if child_counts[child_tag] > 1:
            child_prefix = f"{current_path}.{child_tag}[{idx}]"
        else:
            child_prefix = f"{current_path}.{child_tag}"

        if child.text and child.text.strip():
            pairs.append((child_prefix, _normalize_value(child.text.strip())))
        for attr_name, attr_value in child.attrib.items():
            pairs.append((f"{child_prefix}@{attr_name}", _normalize_value(attr_value)))
        for grandchild in child:
            pairs.extend(flatten_xml(grandchild, child_prefix))

    return pairs


def _normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value).strip()


def extract_path_values(dataset: Dataset) -> list[tuple[str, str]]:
    """Extract path-value pairs from a dataset based on its modality."""
    if dataset.modality == Modality.STRUCTURED_JSON:
        data = dataset.data
        if isinstance(data, list):
            pairs = []
            for i, record in enumerate(data):
                sub_pairs = flatten_json(record, prefix=f"row[{i}]")
                pairs.extend(sub_pairs)
            return pairs
        return flatten_json(data)

    elif dataset.modality == Modality.STRUCTURED_CSV:
        return flatten_csv(dataset.data)

    elif dataset.modality == Modality.SEMI_STRUCTURED_XML:
        return flatten_xml(dataset.data)

    else:
        raise ValueError(
            f"Path-value extraction not supported for modality: {dataset.modality}"
        )


def extract_paths(dataset: Dataset) -> set[str]:
    """Extract only the paths (schema skeleton) from a dataset."""
    pairs = extract_path_values(dataset)
    return {p for p, _ in pairs}


def extract_path_value_set(dataset: Dataset) -> set[tuple[str, str]]:
    """Extract path-value pairs as a set for Jaccard computation."""
    return set(extract_path_values(dataset))


def dataset_to_text(dataset: Dataset) -> str:
    """Serialize a dataset to a text representation for embedding computation."""
    if dataset.modality == Modality.UNSTRUCTURED_TEXT:
        return dataset.data

    pairs = extract_path_values(dataset)
    return "\n".join(f"{path}: {value}" for path, value in pairs)
