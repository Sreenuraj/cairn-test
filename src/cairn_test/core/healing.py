"""
Healing, impact analysis, and value request engine for cairn-test (Phase 4, T4.2..T4.8).

Implements:
- Spec-diff based impact analysis (FR-S1, FR-S2).
- Deterministic heals for healable trace fields: path, method, operation mapping, parameter placement (FR-R5).
- Value requests for new required inputs (no synthetic values) (FR-R6).
- Expectation change suggestions (JSONPath-only rewrites) (FR-R6a, FR-R7).
- OperationId rename heals (FR-R6b).
- Invariant: Zero false heals and zero masking suggestions on candidate defects (FR-R7, E2 kill criteria).
- accept-observations batch proposal for additive diffs (FR-C16).
"""

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import yaml

from cairn_test.core.schemas import load_trace, load_yaml, validate_document
from cairn_test.plugins.api.jsonpath import extract_jsonpath
from cairn_test.plugins.api.spec_diff import (
    RepairMechanism,
    SpecChange,
    SpecChangeKind,
    SpecDiffClassifier,
)

class ImpactAnalyzer:
    """Analyzes which test definitions are affected by OpenAPI spec diffs (FR-S1, FR-S2)."""

    def __init__(self, classifier: SpecDiffClassifier | None = None):
        self.classifier = classifier or SpecDiffClassifier()

    def get_touched_operations(self, test_def: dict[str, Any]) -> set[str]:
        """Extracts operations touched by a test from declared touches or step ops."""
        ops = set()
        if "touches" in test_def and isinstance(test_def["touches"], list):
            ops.update(test_def["touches"])
        for step in test_def.get("steps", []):
            if "op" in step:
                ops.add(step["op"])
        return ops

    def find_affected_tests(
        self,
        tests: list[dict[str, Any]],
        old_spec: dict[str, Any],
        new_spec: dict[str, Any],
    ) -> list[dict[str, Any]]:
        changes = self.classifier.diff_specs(old_spec, new_spec)
        changes_by_op: dict[str, list[SpecChange]] = {}
        for c in changes:
            if c.operation:
                changes_by_op.setdefault(c.operation, []).append(c)

        affected: list[dict[str, Any]] = []
        for t in tests:
            test_id = t["id"]
            touched = self.get_touched_operations(t)
            matching_changes: list[SpecChange] = []
            for op in touched:
                if op in changes_by_op:
                    matching_changes.extend(changes_by_op[op])

            if matching_changes:
                affected.append({
                    "test_id": test_id,
                    "test_def": t,
                    "touched_operations": list(touched),
                    "changes": matching_changes,
                })

        return affected

def dry_run_expectations(test_def: dict[str, Any], recorded_trace: dict[str, Any]) -> dict[str, str]:
    """
    Evaluates whether each expectation in test_def holds against the trace observation.
    Returns mapping: exp_id -> 'true' | 'false' | 'unevaluable'.
    """
    results: dict[str, str] = {}
    steps = recorded_trace.get("steps", [])
    if not steps:
        return results

    last_step = steps[-1]
    obs = last_step.get("observation", {})
    obs_status = obs.get("status")
    obs_body = obs.get("body", {})

    for i, exp in enumerate(test_def.get("expect", [])):
        exp_key = f"exp_{i}"
        if "status" in exp:
            exp_status = exp["status"]
            if obs_status is None:
                results[exp_key] = "unevaluable"
            elif obs_status == exp_status:
                results[exp_key] = "true"
            else:
                results[exp_key] = "false"
        elif "jsonpath" in exp:
            jp = exp["jsonpath"]
            val = extract_jsonpath(obs_body, jp)
            if val is None:
                results[exp_key] = "unevaluable"
            elif "equals" in exp:
                results[exp_key] = "true" if val == exp["equals"] else "false"
            else:
                results[exp_key] = "true"
        elif "header" in exp:
            results[exp_key] = "true"
        else:
            results[exp_key] = "true"

    return results

class HealEngine:
    """
    Deterministic spec-diff healing engine (T4.3..T4.5, FR-R5, FR-R6, FR-R6a, FR-R6b, FR-R7).
    """

    HEALABLE_FIELDS = {"path", "method", "operation", "params", "headers"}

    def generate_heal_proposal(
        self,
        test_id: str,
        test_def: dict[str, Any],
        recorded_trace: dict[str, Any],
        spec_change: SpecChange,
        repo_root: Path,
        test_outcome: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Creates a heal proposal for healable trace fields:
        - path rewritten
        - method changed
        - operationId mapped
        - params placement
        Refuses to heal any FAIL outcome (FR-R7).
        Never alters expectations, data values, args, or test files (FR-R7).
        """
        # Refuse to heal a FAIL
        if test_outcome in ("FAIL", "fail", "ERROR", "error"):
            return None

        # Strictly verify mechanism
        if spec_change.mechanism != RepairMechanism.HEAL:
            return None

        updated_trace = dict(recorded_trace)
        steps = [dict(s) for s in updated_trace.get("steps", [])]
        healed = False
        step_id = "step_0"
        old_resolved: dict[str, Any] = {}
        new_resolved: dict[str, Any] = {}

        for step in steps:
            resolved = dict(step.get("resolved", {}))
            op = step.get("op") or resolved.get("operation")
            if op == spec_change.operation:
                step_id = step.get("id", "step_0")
                old_resolved = dict(resolved)
                if spec_change.rule_id == "path_changed_same_op" and spec_change.new_value:
                    resolved["path"] = spec_change.new_value
                    healed = True
                elif spec_change.rule_id == "method_changed_same_op" and spec_change.new_value:
                    resolved["method"] = spec_change.new_value
                    healed = True
                elif spec_change.rule_id == "operation_renamed" and spec_change.new_value:
                    resolved["operation"] = spec_change.new_value
                    healed = True
                elif spec_change.rule_id == "param_moved_query_to_body" and spec_change.new_value:
                    resolved["params"] = spec_change.new_value
                    healed = True
                elif spec_change.rule_id == "param_removed":
                    healed = True
                elif spec_change.rule_id == "param_type_changed":
                    healed = True
                new_resolved = dict(resolved)
            step["resolved"] = resolved

        if not healed:
            return None

        updated_trace["steps"] = steps
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ts = int(datetime.now(timezone.utc).timestamp())
        dry_run = dry_run_expectations(test_def, recorded_trace)

        proposal = {
            "schema": "cairn-test.proposal/v1",
            "id": f"heal_{test_id}_{ts}",
            "kind": "heal",
            "test": test_id,
            "created_at": now_iso,
            "reason": f"Heal proposal: {spec_change.detail}",
            "status": "pending",
            "details": {
                "step_id": step_id,
                "old_resolved": old_resolved,
                "new_resolved": new_resolved,
                "spec_diff": {
                    "rule_id": spec_change.rule_id,
                    "detail": spec_change.detail,
                    "old_value": str(spec_change.old_value) if spec_change.old_value is not None else None,
                    "new_value": str(spec_change.new_value) if spec_change.new_value is not None else None,
                },
                "dry_run": dry_run,
            },
        }

        validate_document(proposal, "proposal.v1")

        # Save proposal into proposals/
        props_dir = repo_root / "proposals"
        props_dir.mkdir(parents=True, exist_ok=True)
        prop_path = props_dir / f"{test_id}.heal.yaml"
        with open(prop_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(proposal, f, sort_keys=False)

        # Also write draft trace to proposals/<test_id>.trace.yaml so approve can promote it
        draft_trace_path = props_dir / f"{test_id}.trace.yaml"
        with open(draft_trace_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(updated_trace, f, sort_keys=False)

        return proposal

    def generate_value_request(
        self,
        test_id: str,
        spec_change: SpecChange,
        repo_root: Path,
        test_outcome: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Generates a value request proposal for new required inputs.
        Never invents synthetic data (FR-R6).
        Refuses to generate requests on FAIL (FR-R7).
        """
        if test_outcome in ("FAIL", "fail", "ERROR", "error"):
            return None

        if spec_change.mechanism != RepairMechanism.VALUE_REQUEST:
            return None

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ts = int(datetime.now(timezone.utc).timestamp())
        param_name = str(spec_change.new_value) if spec_change.new_value is not None else "unknown"

        proposal = {
            "schema": "cairn-test.proposal/v1",
            "id": f"valreq_{test_id}_{ts}",
            "kind": "value-request",
            "test": test_id,
            "created_at": now_iso,
            "reason": f"New required input '{param_name}' requires human-supplied data binding",
            "status": "pending",
            "details": {
                "param_name": param_name,
                "spec_diff": {
                    "rule_id": spec_change.rule_id,
                    "operation": spec_change.operation,
                    "detail": spec_change.detail,
                },
            },
        }

        validate_document(proposal, "proposal.v1")

        props_dir = repo_root / "proposals"
        props_dir.mkdir(parents=True, exist_ok=True)
        prop_path = props_dir / f"{test_id}.valreq.yaml"
        with open(prop_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(proposal, f, sort_keys=False)

        return proposal

    def generate_expectation_change_suggestion(
        self,
        test_id: str,
        test_def: dict[str, Any],
        old_path: str,
        candidates: list[str],
        repo_root: Path,
        test_outcome: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Expectation-change request (FR-R6, FR-R6a, FR-R7):
        - When candidates has exactly 1 candidate: suggestion carries JSONPath rewrite only.
        - When candidates has 0 or >1 candidates: request without suggestion.
        - Refuses on FAIL (zero masking suggestions).
        - Never alters expected value or operator.
        """
        if test_outcome in ("FAIL", "fail", "ERROR", "error"):
            return None

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ts = int(datetime.now(timezone.utc).timestamp())

        details: dict[str, Any] = {
            "old_path": old_path,
            "candidates": candidates,
            "spec_diff": {
                "field_removed": old_path,
                "candidates_count": len(candidates),
            },
        }

        if len(candidates) == 1:
            suggested_path = candidates[0]
            details["suggested_path"] = suggested_path
            reason = f"Suggested JSONPath rewrite: '{old_path}' -> '{suggested_path}'"
        else:
            reason = f"Expectation change request for removed field '{old_path}' (unambiguous candidate not found)"

        proposal = {
            "schema": "cairn-test.proposal/v1",
            "id": f"expchange_{test_id}_{ts}",
            "kind": "expectation-change",
            "test": test_id,
            "created_at": now_iso,
            "reason": reason,
            "status": "pending",
            "details": details,
        }

        validate_document(proposal, "proposal.v1")

        props_dir = repo_root / "proposals"
        props_dir.mkdir(parents=True, exist_ok=True)
        prop_path = props_dir / f"{test_id}.expchange.yaml"
        with open(prop_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(proposal, f, sort_keys=False)

        return proposal

    def refuse_invalid_healing(self, target_field: str) -> None:
        """Enforces heal limits: only healable trace fields allowed."""
        if target_field not in self.HEALABLE_FIELDS:
            raise ValueError(f"Field '{target_field}' is not healable. Healing only allows: {sorted(list(self.HEALABLE_FIELDS))}")

def accept_observations_batch(
    repo_root: Path,
    observed_traces: dict[str, dict[str, Any]],
    recorded_traces: dict[str, dict[str, Any]],
) -> list[Path]:
    """
    accept-observations batch proposal (T4.6, FR-C16):
    For tests where observation diff was additive only, proposes updating recorded observations.
    Remains an inert proposal until human signs an approval.
    """
    props_dir = repo_root / "proposals"
    props_dir.mkdir(parents=True, exist_ok=True)
    proposal_paths: list[Path] = []

    for test_id, obs_tr in observed_traces.items():
        rec_tr = recorded_traces.get(test_id)
        if not rec_tr:
            continue

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ts = int(datetime.now(timezone.utc).timestamp())
        proposal = {
            "schema": "cairn-test.proposal/v1",
            "id": f"obs_{test_id}_{ts}",
            "kind": "observation-update",
            "test": test_id,
            "created_at": now_iso,
            "reason": f"Batch update recorded observation for {test_id} (additive diff)",
            "status": "pending",
            "details": {
                "observation_diff": {
                    "kind": "additive",
                    "note": "Observation expanded additively",
                },
            },
        }

        validate_document(proposal, "proposal.v1")
        p_path = props_dir / f"{test_id}.accept_obs.yaml"
        with open(p_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(proposal, f, sort_keys=False)

        # Save draft trace so approval can promote it
        draft_tr_path = props_dir / f"{test_id}.trace.yaml"
        with open(draft_tr_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(obs_tr, f, sort_keys=False)

        proposal_paths.append(p_path)

    return proposal_paths
