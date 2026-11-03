"""
OpenAPI 3.0 / 3.1 ingestion, $ref resolution, and normalized operation hashing (T2.1, FR-A1).
"""

from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any
import yaml

@dataclass
class OperationDef:
    operation_id: str
    method: str
    path: str
    summary: str = ""
    parameters: list[dict[str, Any]] = field(default_factory=list)
    request_body: dict[str, Any] | None = None
    responses: dict[str, dict[str, Any]] = field(default_factory=dict)
    op_hash: str = ""

def canonical_hash(obj: Any) -> str:
    """Computes SHA-256 hash of canonically serialized JSON representation."""
    canonical_bytes = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()

class OpenAPISpec:
    """Parses OpenAPI 3.0/3.1 specs, resolves $refs, and normalizes operations."""

    def __init__(self, raw: dict[str, Any]):
        self.raw = raw
        self.spec_hash = canonical_hash(raw)
        self.operations_by_id: dict[str, OperationDef] = {}
        self.operations_by_path_method: dict[tuple[str, str], OperationDef] = {}
        self._parse()

    @classmethod
    def load(cls, path_or_content: Path | str | dict[str, Any]) -> OpenAPISpec:
        if isinstance(path_or_content, dict):
            return cls(path_or_content)
        p = Path(path_or_content)
        if p.is_file():
            with open(p, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
            return cls(content or {})
        # Treat as YAML/JSON string
        content = yaml.safe_load(str(path_or_content))
        return cls(content or {})

    def resolve_ref(self, ref: str, visited: set[str] | None = None) -> Any:
        """Resolves local #/components/... references."""
        if not ref.startswith("#/"):
            return {"$ref": ref}  # External refs returned as-is
        
        seen = set(visited or set())
        if ref in seen:
            return {}  # Prevent circular loop
        seen.add(ref)

        parts = ref.lstrip("#/").split("/")
        curr = self.raw
        for part in parts:
            if isinstance(curr, dict) and part in curr:
                curr = curr[part]
            else:
                return {}

        if isinstance(curr, dict) and "$ref" in curr:
            return self.resolve_ref(curr["$ref"], seen)
        return curr

    def resolve_schema(self, schema: Any, visited: set[str] | None = None) -> Any:
        """Recursively resolves all $ref occurrences in a schema dict or list."""
        if isinstance(schema, dict):
            if "$ref" in schema:
                resolved = self.resolve_ref(schema["$ref"], visited)
                # Combine remaining keys if any
                merged = {k: v for k, v in schema.items() if k != "$ref"}
                merged.update(self.resolve_schema(resolved, visited))
                return merged
            return {k: self.resolve_schema(v, visited) for k, v in schema.items()}
        elif isinstance(schema, list):
            return [self.resolve_schema(item, visited) for item in schema]
        return schema

    def _parse(self) -> None:
        paths = self.raw.get("paths", {})
        for path_str, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            
            # Common path parameters
            common_params = path_item.get("parameters", [])

            for method_str, op_obj in path_item.items():
                method_upper = method_str.upper()
                if method_upper not in ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE"]:
                    continue
                if not isinstance(op_obj, dict):
                    continue

                op_id = op_obj.get("operationId") or f"{method_upper.lower()}_{path_str.replace('/', '_').strip('_')}"
                summary = op_obj.get("summary", "")

                # Combine & resolve parameters
                all_params = list(common_params) + list(op_obj.get("parameters", []))
                resolved_params = []
                for p in all_params:
                    if "$ref" in p:
                        p = self.resolve_ref(p["$ref"])
                    p_res = self.resolve_schema(p)
                    resolved_params.append(p_res)

                # Sort parameters canonically by (in, name)
                resolved_params.sort(key=lambda x: (x.get("in", ""), x.get("name", "")))

                # Resolve requestBody
                req_body = op_obj.get("requestBody")
                if req_body:
                    if "$ref" in req_body:
                        req_body = self.resolve_ref(req_body["$ref"])
                    req_body = self.resolve_schema(req_body)

                # Resolve responses
                responses = {}
                for status_code, resp_obj in op_obj.get("responses", {}).items():
                    if "$ref" in resp_obj:
                        resp_obj = self.resolve_ref(resp_obj["$ref"])
                    responses[str(status_code)] = self.resolve_schema(resp_obj)

                # Compute normalized operation hash
                norm_op = {
                    "operationId": op_id,
                    "method": method_upper,
                    "path": path_str,
                    "parameters": resolved_params,
                    "requestBody": req_body,
                    "responses": responses,
                }
                op_hash = canonical_hash(norm_op)

                op_def = OperationDef(
                    operation_id=op_id,
                    method=method_upper,
                    path=path_str,
                    summary=summary,
                    parameters=resolved_params,
                    request_body=req_body,
                    responses=responses,
                    op_hash=op_hash,
                )

                self.operations_by_id[op_id] = op_def
                self.operations_by_path_method[(path_str, method_upper)] = op_def

    def get_operation(self, operation_id: str) -> OperationDef:
        if operation_id not in self.operations_by_id:
            raise KeyError(f"Operation ID '{operation_id}' not found in OpenAPI spec.")
        return self.operations_by_id[operation_id]
