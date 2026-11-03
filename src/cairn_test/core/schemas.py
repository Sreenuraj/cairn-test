"""
Schema loaders and validators for cairn-test core (FR-C1, FR-C2).

Supports loading and validating:
- cairn-test.test/v1
- cairn-test.trace/v1
- cairn-test.approval/v1
- cairn-test.proposal/v1
- cairn-test.event/v1
- cairn-test.result/v1
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any
import jsonschema
import yaml

KNOWN_SCHEMAS: dict[str, str] = {
    "cairn-test.test/v1": "test.v1.json",
    "cairn-test.trace/v1": "trace.v1.json",
    "cairn-test.approval/v1": "approval.v1.json",
    "cairn-test.proposal/v1": "proposal.v1.json",
    "cairn-test.event/v1": "event.v1.json",
    "cairn-test.result/v1": "result.v1.json",
}

SUPPORTED_KINDS: dict[str, list[str]] = {
    "test": ["cairn-test.test/v1"],
    "trace": ["cairn-test.trace/v1"],
    "approval": ["cairn-test.approval/v1"],
    "proposal": ["cairn-test.proposal/v1"],
    "event": ["cairn-test.event/v1"],
    "result": ["cairn-test.result/v1"],
}

class SchemaVersionError(ValueError):
    """Raised when an unknown or unsupported schema version is encountered."""
    def __init__(self, kind: str, version: str, supported: list[str]):
        msg = (
            f"Unsupported schema version '{version}' for {kind}. "
            f"Supported versions: {supported}. "
            f"Run 'cairn-test migrate' to upgrade stored files."
        )
        super().__init__(msg)
        self.kind = kind
        self.version = version
        self.supported = supported

class SchemaValidationError(ValueError):
    """Raised when a document violates its JSON Schema."""
    def __init__(self, message: str, path: str = ""):
        super().__init__(f"Validation error at '{path}': {message}" if path else f"Validation error: {message}")
        self.path = path

_SCHEMAS_CACHE: dict[str, dict[str, Any]] = {}

def get_schemas_dir() -> Path:
    # First look at project root / schemas
    root = Path(__file__).resolve().parent.parent.parent.parent
    candidate = root / "schemas"
    if candidate.is_dir():
        return candidate
    # Fallback to local cwd schemas
    cwd_candidate = Path.cwd() / "schemas"
    if cwd_candidate.is_dir():
        return cwd_candidate
    raise FileNotFoundError("Could not locate cairn-test 'schemas/' directory.")

def get_schema(schema_id: str) -> dict[str, Any]:
    if schema_id in _SCHEMAS_CACHE:
        return _SCHEMAS_CACHE[schema_id]
    
    filename = KNOWN_SCHEMAS.get(schema_id)
    if not filename:
        raise ValueError(f"Unknown schema identifier: {schema_id}")
    
    path = get_schemas_dir() / filename
    with open(path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    _SCHEMAS_CACHE[schema_id] = schema
    return schema

def validate_doc(doc: dict[str, Any], expected_kind: str | None = None) -> None:
    if not isinstance(doc, dict):
        raise SchemaValidationError("Document must be a dictionary.")

    schema_id = doc.get("schema")
    if not schema_id:
        raise SchemaValidationError("Missing required 'schema' identifier in document.")

    if expected_kind:
        supported = SUPPORTED_KINDS.get(expected_kind, [])
        if schema_id not in supported:
            raise SchemaVersionError(expected_kind, schema_id, supported)

    if schema_id not in KNOWN_SCHEMAS:
        raise SchemaVersionError("unknown", schema_id, list(KNOWN_SCHEMAS.keys()))

    schema = get_schema(schema_id)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: e.path)
    if errors:
        first = errors[0]
        jsonpath = "$." + ".".join(str(p) for p in first.path) if first.path else "$"
        raise SchemaValidationError(first.message, path=jsonpath)

def _read_file_or_data(target: Path | str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(target, dict):
        return target
    p = Path(target)
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {p}")
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise SchemaValidationError(f"Expected YAML object in {p}, got {type(data).__name__}")
    return data

def load_test(target: Path | str | dict[str, Any]) -> dict[str, Any]:
    doc = _read_file_or_data(target)
    validate_doc(doc, expected_kind="test")
    return doc

def load_trace(target: Path | str | dict[str, Any]) -> dict[str, Any]:
    doc = _read_file_or_data(target)
    validate_doc(doc, expected_kind="trace")
    return doc

def load_approval(target: Path | str | dict[str, Any]) -> dict[str, Any]:
    doc = _read_file_or_data(target)
    validate_doc(doc, expected_kind="approval")
    return doc

def load_proposal(target: Path | str | dict[str, Any]) -> dict[str, Any]:
    doc = _read_file_or_data(target)
    validate_doc(doc, expected_kind="proposal")
    return doc

def load_event(target: Path | str | dict[str, Any]) -> dict[str, Any]:
    doc = _read_file_or_data(target)
    validate_doc(doc, expected_kind="event")
    return doc

def load_result(target: Path | str | dict[str, Any]) -> dict[str, Any]:
    doc = _read_file_or_data(target)
    validate_doc(doc, expected_kind="result")
    return doc
