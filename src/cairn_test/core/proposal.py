"""
Proposal generation and review labeling engine (T3.2, T3.3, FR-R2, FR-R3, FR-R8).

Traces and changes are written as inert proposals.
Labels indicate:
- new-test: newly authored test definition.
- new-trace: newly recorded trace.
- observation-updated: observation differs from approved trace.
- expectation-removed: an expectation was removed compared to approved test.
- expectation-loosened: an expectation condition was loosened.
- scope-changed: steps, operations, or tags changed.
"""

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import yaml

from cairn_test.core.schemas import load_yaml, validate_document

def render_step_summary(step: dict[str, Any]) -> str:
    """Generate concise human-readable step summary."""
    op = step.get("op") or step.get("operation") or step.get("id")
    method = step.get("resolved", {}).get("method") or "POST"
    path = step.get("resolved", {}).get("path") or f"/{op}"
    status = step.get("observation", {}).get("status") or 200
    return f"{op} ({method} {path}) -> {status}"

def create_trace_proposal(
    repo_root: Path,
    test_id: str,
    trace_data: dict[str, Any],
    labels: list[str] | None = None,
) -> Path:
    """
    Writes recorded trace as an inert proposal into proposals/<test_id>.proposal.yaml.
    Also saves proposal trace into proposals/<test_id>.trace.yaml.
    """
    props_dir = repo_root / "proposals"
    props_dir.mkdir(parents=True, exist_ok=True)

    now_iso = datetime.now(timezone.utc).isoformat()
    steps_summaries = [render_step_summary(s) for s in trace_data.get("steps", [])]

    # Write trace file into proposals/
    draft_trace_path = props_dir / f"{test_id}.trace.yaml"
    with open(draft_trace_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(trace_data, f, sort_keys=False)

    kind = "observation-update" if "observation-updated" in (labels or []) else "draft"
    proposal_doc = {
        "schema": "cairn-test.proposal/v1",
        "id": f"prop-{test_id}-{int(datetime.now(timezone.utc).timestamp())}".replace(".", "-"),
        "kind": kind,
        "test": test_id,
        "created_at": now_iso,
        "reason": f"Recorded trace for {test_id}",
        "status": "pending",
        "details": {
            "labels": labels or ["new-trace"],
            "summary": f"Recorded trace for {test_id}: " + "; ".join(steps_summaries),
            "steps": steps_summaries,
            "trace": trace_data,
        },
    }

    validate_document(proposal_doc, "proposal.v1")

    proposal_path = props_dir / f"{test_id}.proposal.yaml"
    with open(proposal_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(proposal_doc, f, sort_keys=False)

    return proposal_path

def compute_review_labels(
    repo_root: Path,
    test_id: str,
    current_test_def: dict[str, Any] | None = None,
    current_trace: dict[str, Any] | None = None,
) -> list[str]:
    """
    Computes review labels by comparing current files against approved files:
    - new-test
    - new-trace
    - observation-updated
    - expectation-removed
    - expectation-loosened
    - scope-changed
    """
    labels: list[str] = []

    appr_file = repo_root / "approvals" / f"{test_id}.approval.yaml"
    approved_test_def: dict[str, Any] | None = None
    approved_trace: dict[str, Any] | None = None

    if not appr_file.is_file():
        labels.append("new-test")
        labels.append("new-trace")
        return sorted(list(set(labels)))

    try:
        appr_data = load_yaml(appr_file)
        covers = appr_data.get("covers", {})
    except Exception:
        covers = {}

    test_file_rel = f"tests/{test_id}.test.yaml"
    trace_file_rel = f"traces/{test_id}.trace.yaml"

    if test_file_rel not in covers:
        labels.append("new-test")
    if trace_file_rel not in covers:
        labels.append("new-trace")

    approved_test_path = repo_root / "tests" / f"{test_id}.test.yaml"
    approved_trace_path = repo_root / "traces" / f"{test_id}.trace.yaml"

    if approved_test_path.is_file():
        try:
            approved_test_def = load_yaml(approved_test_path)
        except Exception:
            pass

    if approved_trace_path.is_file():
        try:
            approved_trace = load_yaml(approved_trace_path)
        except Exception:
            pass

    # Compare test definitions
    if current_test_def and approved_test_def:
        # Check scope changed (steps or tags)
        curr_tags = set(current_test_def.get("tags", []))
        appr_tags = set(approved_test_def.get("tags", []))
        curr_ops = [s.get("op") for s in current_test_def.get("steps", [])]
        appr_ops = [s.get("op") for s in approved_test_def.get("steps", [])]

        if curr_tags != appr_tags or curr_ops != appr_ops:
            labels.append("scope-changed")

        # Check expectations
        curr_exps = current_test_def.get("expect", [])
        appr_exps = approved_test_def.get("expect", [])

        if len(curr_exps) < len(appr_exps):
            labels.append("expectation-removed")

        # Check if an expectation was loosened (e.g. range widened)
        for c_exp in curr_exps:
            c_range = c_exp.get("range")
            if c_range and isinstance(c_range, dict):
                # Look for matching expectation in approved
                for a_exp in appr_exps:
                    a_range = a_exp.get("range")
                    if a_range and isinstance(a_range, dict) and c_exp.get("jsonpath") == a_exp.get("jsonpath"):
                        if c_range.get("min", 0) < a_range.get("min", 0) or c_range.get("max", 0) > a_range.get("max", 0):
                            labels.append("expectation-loosened")

    # Compare traces
    if current_trace and approved_trace:
        # Compare observations per step
        curr_steps = {s["id"]: s.get("observation", {}) for s in current_trace.get("steps", [])}
        appr_steps = {s["id"]: s.get("observation", {}) for s in approved_trace.get("steps", [])}

        if curr_steps != appr_steps:
            labels.append("observation-updated")

    if not labels:
        labels.append("no-changes")

    return sorted(list(set(labels)))
