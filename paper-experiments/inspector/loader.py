"""Dataset loader and modality detection."""

import csv
import io
import json
import os
import xml.etree.ElementTree as ET
from enum import Enum
from typing import Any


class Modality(Enum):
    STRUCTURED_JSON = "structured_json"
    STRUCTURED_CSV = "structured_csv"
    SEMI_STRUCTURED_XML = "semi_structured_xml"
    UNSTRUCTURED_TEXT = "unstructured_text"


class Dataset:
    """Represents a loaded dataset with its content and metadata."""

    def __init__(self, data: Any, modality: Modality, source_path: str,
                 unit_meta: dict[str, str] | None = None):
        self.data = data
        self.modality = modality
        self.source_path = source_path
        self.filename = os.path.basename(source_path)
        self.unit_meta: dict[str, str] = dict(unit_meta) if unit_meta else {}

    def __repr__(self):
        return f"Dataset(modality={self.modality.value}, source={self.filename})"

    @property
    def is_structured(self) -> bool:
        return self.modality in (Modality.STRUCTURED_JSON, Modality.STRUCTURED_CSV)

    @property
    def is_semi_structured(self) -> bool:
        return self.modality == Modality.SEMI_STRUCTURED_XML

    @property
    def is_unstructured(self) -> bool:
        return self.modality == Modality.UNSTRUCTURED_TEXT


def detect_modality(filepath: str) -> Modality:
    """Detect dataset modality from file extension and content inspection."""
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".json":
        return Modality.STRUCTURED_JSON
    elif ext == ".csv":
        return Modality.STRUCTURED_CSV
    elif ext == ".xml":
        return Modality.SEMI_STRUCTURED_XML
    elif ext in (".txt", ".log"):
        return Modality.UNSTRUCTURED_TEXT

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        sample = f.read(1024)

    sample_stripped = sample.lstrip()
    if sample_stripped.startswith("{") or sample_stripped.startswith("["):
        return Modality.STRUCTURED_JSON
    if sample_stripped.startswith("<?xml") or sample_stripped.startswith("<"):
        return Modality.SEMI_STRUCTURED_XML

    try:
        dialect = csv.Sniffer().sniff(sample)
        if dialect:
            return Modality.STRUCTURED_CSV
    except csv.Error:
        pass

    return Modality.UNSTRUCTURED_TEXT


def load_json(filepath: str) -> Any:
    """Load a JSON file, handling both objects and arrays."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def load_csv(filepath: str) -> list[dict]:
    """Load a CSV file as a list of row dictionaries."""
    with open(filepath, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def load_xml(filepath: str) -> ET.Element:
    """Load an XML file and return the root element."""
    tree = ET.parse(filepath)
    return tree.getroot()


def load_text(filepath: str) -> str:
    """Load a plain text or log file."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def load_dataset(filepath: str) -> Dataset:
    """Load a dataset from file, auto-detecting modality."""
    modality = detect_modality(filepath)

    if modality == Modality.STRUCTURED_JSON:
        data = load_json(filepath)
    elif modality == Modality.STRUCTURED_CSV:
        data = load_csv(filepath)
    elif modality == Modality.SEMI_STRUCTURED_XML:
        data = load_xml(filepath)
    elif modality == Modality.UNSTRUCTURED_TEXT:
        data = load_text(filepath)
    else:
        raise ValueError(f"Unsupported modality: {modality}")

    return Dataset(data=data, modality=modality, source_path=filepath)


def load_from_string(content: str, modality: Modality, name: str = "<string>") -> Dataset:
    """Load a dataset from a string, given a known modality."""
    if modality == Modality.STRUCTURED_JSON:
        data = json.loads(content)
    elif modality == Modality.STRUCTURED_CSV:
        reader = csv.DictReader(io.StringIO(content))
        data = list(reader)
    elif modality == Modality.SEMI_STRUCTURED_XML:
        data = ET.fromstring(content)
    elif modality == Modality.UNSTRUCTURED_TEXT:
        data = content
    else:
        raise ValueError(f"Unsupported modality: {modality}")

    return Dataset(data=data, modality=modality, source_path=name)
