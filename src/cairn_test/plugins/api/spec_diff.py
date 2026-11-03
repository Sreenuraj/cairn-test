"""
OpenAPI spec diff classifier and impact analyzer (T4.1, T4.2, FR-A7, FR-S1, FR-S2).

Classifies request-side and spec changes according to plan.md section 14:
- New optional parameter -> additive (none)
- Enum value added to response -> additive (none)
- New required parameter -> breaking (value-request)
- Path changed with unchanged operationId -> breaking (heal)
- Method changed with unchanged operationId -> breaking (heal)
- Parameter removed -> breaking (heal)
- Parameter type changed -> breaking (heal)
- Parameter placement moved (e.g. query to body) -> breaking (heal)
- OperationId renamed (method/path unchanged) -> breaking (heal)
- Enum value removed from response -> breaking (expectation-change)
- Response field removed/renamed -> breaking (expectation-change)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

class SpecChangeKind(str, Enum):
    ADDITIVE = "additive"
    BREAKING = "breaking"
    IDENTICAL = "identical"

class RepairMechanism(str, Enum):
    NONE = "none"
    HEAL = "heal"
    VALUE_REQUEST = "value-request"
    EXPECTATION_CHANGE = "expectation-change"

@dataclass
class SpecChange:
    kind: SpecChangeKind
    mechanism: RepairMechanism
    rule_id: str
    detail: str
    operation: str | None = None
    path: str | None = None
    method: str | None = None
    old_value: Any = None
    new_value: Any = None
    candidates: list[str] = field(default_factory=list)

def _extract_schema_properties(schema_dict: dict[str, Any]) -> dict[str, str]:
    """Extract flat property_name -> type mapping from a JSON schema object."""
    props = schema_dict.get("properties", {})
    res: dict[str, str] = {}
    if isinstance(props, dict):
        for k, v in props.items():
            if isinstance(v, dict):
                res[k] = v.get("type", "unknown")
            else:
                res[k] = "unknown"
    return res

def find_response_field_candidates(
    recorded_op: dict[str, Any],
    observed_op: dict[str, Any],
) -> list[tuple[str, str, list[str]]]:
    """
    Finds removed response fields and matching candidates of the same type (FR-R6a).
    Returns list of tuples: (removed_field_name, field_type, matching_candidate_names).
    """
    rec_resp = recorded_op.get("responses", {})
    obs_resp = observed_op.get("responses", {})

    # Extract 200/201 application/json schemas
    rec_schema: dict[str, Any] = {}
    obs_schema: dict[str, Any] = {}

    for code in ("200", "201", "default"):
        if code in rec_resp and isinstance(rec_resp[code], dict):
            c = rec_resp[code].get("content", {}).get("application/json", {}).get("schema", {})
            if c:
                rec_schema = c
                break
        if code in obs_resp and isinstance(obs_resp[code], dict):
            c = obs_resp[code].get("content", {}).get("application/json", {}).get("schema", {})
            if c:
                obs_schema = c
                break

    rec_props = _extract_schema_properties(rec_schema)
    obs_props = _extract_schema_properties(obs_schema)

    results: list[tuple[str, str, list[str]]] = []
    removed = [p for p in rec_props if p not in obs_props]
    added = [p for p in obs_props if p not in rec_props]

    for rem in removed:
        rem_type = rec_props[rem]
        # Same-type candidates
        cands = [a for a in added if obs_props[a] == rem_type]
        results.append((rem, rem_type, cands))

    return results

def classify_operation_diff(recorded_op: dict[str, Any], observed_op: dict[str, Any]) -> list[SpecChange]:
    """Classifies differences between a recorded operation spec and an observed operation spec."""
    changes: list[SpecChange] = []
    op_name = observed_op.get("op") or recorded_op.get("op") or "unknown"

    # 1. Path changed with unchanged operationId
    rec_path = recorded_op.get("path")
    obs_path = observed_op.get("path")
    if rec_path and obs_path and rec_path != obs_path:
        changes.append(
            SpecChange(
                kind=SpecChangeKind.BREAKING,
                mechanism=RepairMechanism.HEAL,
                rule_id="path_changed_same_op",
                detail=f"Path changed from {rec_path} to {obs_path}",
                operation=op_name,
                old_value=rec_path,
                new_value=obs_path,
            )
        )

    # 2. Method changed with unchanged operationId
    rec_method = recorded_op.get("method", "").upper() if recorded_op.get("method") else None
    obs_method = observed_op.get("method", "").upper() if observed_op.get("method") else None
    if rec_method and obs_method and rec_method != obs_method:
        changes.append(
            SpecChange(
                kind=SpecChangeKind.BREAKING,
                mechanism=RepairMechanism.HEAL,
                rule_id="method_changed_same_op",
                detail=f"Method changed from {rec_method} to {obs_method}",
                operation=op_name,
                old_value=rec_method,
                new_value=obs_method,
            )
        )

    # 3. Parameter placement moved (e.g. query to body)
    rec_params_map = recorded_op.get("params")
    obs_params_map = observed_op.get("params")
    if isinstance(rec_params_map, dict) and isinstance(obs_params_map, dict):
        if rec_params_map != obs_params_map:
            changes.append(
                SpecChange(
                    kind=SpecChangeKind.BREAKING,
                    mechanism=RepairMechanism.HEAL,
                    rule_id="param_moved_query_to_body",
                    detail=f"Parameter placement changed from {rec_params_map} to {obs_params_map}",
                    operation=op_name,
                    old_value=rec_params_map,
                    new_value=obs_params_map,
                )
            )

    # 4. Parameters list diffs
    rec_params = {p["name"]: p for p in recorded_op.get("parameters", []) if isinstance(p, dict)}
    obs_params = {p["name"]: p for p in observed_op.get("parameters", []) if isinstance(p, dict)}

    # New parameters added
    for p_name, p_spec in obs_params.items():
        if p_name not in rec_params:
            is_req = p_spec.get("required", False)
            if is_req:
                changes.append(
                    SpecChange(
                        kind=SpecChangeKind.BREAKING,
                        mechanism=RepairMechanism.VALUE_REQUEST,
                        rule_id="param_required_added",
                        detail=f"New required parameter added: {p_name}",
                        operation=op_name,
                        new_value=p_name,
                    )
                )
            else:
                changes.append(
                    SpecChange(
                        kind=SpecChangeKind.ADDITIVE,
                        mechanism=RepairMechanism.NONE,
                        rule_id="param_optional_added",
                        detail=f"New optional parameter added: {p_name}",
                        operation=op_name,
                        new_value=p_spec,
                    )
                )

    # Parameters removed
    for p_name, p_spec in rec_params.items():
        if p_name not in obs_params:
            changes.append(
                SpecChange(
                    kind=SpecChangeKind.BREAKING,
                    mechanism=RepairMechanism.HEAL,
                    rule_id="param_removed",
                    detail=f"Parameter removed: {p_name}",
                    operation=op_name,
                    old_value=p_spec,
                )
            )
        else:
            # Check type changed
            rec_type = p_spec.get("schema", {}).get("type")
            obs_type = obs_params[p_name].get("schema", {}).get("type")
            if rec_type and obs_type and rec_type != obs_type:
                changes.append(
                    SpecChange(
                        kind=SpecChangeKind.BREAKING,
                        mechanism=RepairMechanism.HEAL,
                        rule_id="param_type_changed",
                        detail=f"Parameter {p_name} type changed from {rec_type} to {obs_type}",
                        operation=op_name,
                        old_value=rec_type,
                        new_value=obs_type,
                    )
                )

    # 5. Request body schema required fields
    rec_body = recorded_op.get("requestBody", {})
    obs_body = observed_op.get("requestBody", {})
    rec_schema = rec_body.get("content", {}).get("application/json", {}).get("schema", {})
    obs_schema = obs_body.get("content", {}).get("application/json", {}).get("schema", {})

    rec_req = set(rec_schema.get("required", []))
    obs_req = set(obs_schema.get("required", []))
    new_required_fields = obs_req - rec_req
    for f in sorted(new_required_fields):
        changes.append(
            SpecChange(
                kind=SpecChangeKind.BREAKING,
                mechanism=RepairMechanism.VALUE_REQUEST,
                rule_id="param_required_added",
                detail=f"New required body field: {f}",
                operation=op_name,
                new_value=f,
            )
        )

    # 6. Response schema enum values
    rec_resp_schema = recorded_op.get("response_schema", {})
    obs_resp_schema = observed_op.get("response_schema", {})
    for field_name, rec_f in rec_resp_schema.items():
        if field_name in obs_resp_schema:
            obs_f = obs_resp_schema[field_name]
            rec_enums = set(rec_f.get("enum", []))
            obs_enums = set(obs_f.get("enum", []))
            added_enums = obs_enums - rec_enums
            removed_enums = rec_enums - obs_enums

            if added_enums:
                changes.append(
                    SpecChange(
                        kind=SpecChangeKind.ADDITIVE,
                        mechanism=RepairMechanism.NONE,
                        rule_id="enum_value_added_to_response",
                        detail=f"Enum value(s) added to response field {field_name}: {sorted(list(added_enums))}",
                        operation=op_name,
                        new_value=sorted(list(added_enums)),
                    )
                )
            if removed_enums:
                changes.append(
                    SpecChange(
                        kind=SpecChangeKind.BREAKING,
                        mechanism=RepairMechanism.EXPECTATION_CHANGE,
                        rule_id="enum_value_removed_from_response",
                        detail=f"Enum value(s) removed from response field {field_name}: {sorted(list(removed_enums))}",
                        operation=op_name,
                        old_value=sorted(list(removed_enums)),
                    )
                )

    # 7. Response field removed/renamed candidates (FR-R6a)
    if "responses" in recorded_op and "responses" in observed_op:
        for rem_field, f_type, candidates in find_response_field_candidates(recorded_op, observed_op):
            changes.append(
                SpecChange(
                    kind=SpecChangeKind.BREAKING,
                    mechanism=RepairMechanism.EXPECTATION_CHANGE,
                    rule_id="response_field_removed_or_renamed",
                    detail=f"Response field '{rem_field}' removed (type {f_type}, candidates: {candidates})",
                    operation=op_name,
                    old_value=rem_field,
                    candidates=candidates,
                )
            )

    return changes

class SpecDiffClassifier:
    """Classifies full OpenAPI specification diffs."""

    def diff_specs(self, old_spec: dict[str, Any], new_spec: dict[str, Any]) -> list[SpecChange]:
        changes: list[SpecChange] = []
        old_ops = self._extract_operations(old_spec)
        new_ops = self._extract_operations(new_spec)

        # Match by operationId
        for op_id, o_op in old_ops.items():
            if op_id in new_ops:
                n_op = new_ops[op_id]
                changes.extend(classify_operation_diff(o_op, n_op))
            else:
                # Check if operation was renamed (same path, method, and schemas)
                match = None
                for n_id, candidate in new_ops.items():
                    if candidate.get("path") == o_op.get("path") and candidate.get("method") == o_op.get("method"):
                        match = (n_id, candidate)
                        break
                if match:
                    n_id, candidate = match
                    changes.append(
                        SpecChange(
                            kind=SpecChangeKind.BREAKING,
                            mechanism=RepairMechanism.HEAL,
                            rule_id="operation_renamed",
                            detail=f"OperationId renamed from {op_id} to {n_id}",
                            operation=op_id,
                            old_value=op_id,
                            new_value=n_id,
                        )
                    )
                else:
                    changes.append(
                        SpecChange(
                            kind=SpecChangeKind.BREAKING,
                            mechanism=RepairMechanism.NONE,
                            rule_id="operation_removed",
                            detail=f"Operation removed: {op_id}",
                            operation=op_id,
                        )
                    )
        return changes

    def _extract_operations(self, spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
        ops: dict[str, dict[str, Any]] = {}
        paths = spec.get("paths", {})
        for path, p_item in paths.items():
            if not isinstance(p_item, dict):
                continue
            for method, m_item in p_item.items():
                if method.lower() in ["get", "post", "put", "patch", "delete", "options", "head"] and isinstance(m_item, dict):
                    op_id = m_item.get("operationId") or f"{method.lower()}_{path.replace('/', '_')}"
                    ops[op_id] = {
                        "op": op_id,
                        "path": path,
                        "method": method.upper(),
                        "parameters": m_item.get("parameters", []),
                        "requestBody": m_item.get("requestBody", {}),
                        "responses": m_item.get("responses", {}),
                    }
        return ops
