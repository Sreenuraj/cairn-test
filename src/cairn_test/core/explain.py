"""
Explanation engine for cairn-test core (T1.11, FR-G2, FR-O7).

Reconstructs a structured explanation of any test outcome from stored artifacts alone:
- Planning decision
- Step executions and timings
- Observation diffs
- Expectation evaluations
"""

from __future__ import annotations
import json
from typing import Any
from cairn_test.core.events import EventStore

def explain_test(run_id: str, test_id: str, store: EventStore) -> dict[str, Any]:
    events = store.query_events(run_id)
    if not events:
        return {"error": f"No events found for run '{run_id}'"}

    test_events = [
        e for e in events
        if e.get("payload", {}).get("test_id") == test_id
    ]

    planned_event = next((e for e in test_events if e["type"] == "test.planned"), None)
    finished_event = next((e for e in test_events if e["type"] == "test.finished"), None)

    # Query results table
    result_row = None
    import sqlite3
    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM results WHERE run_id = ? AND test_id = ?",
            (run_id, test_id),
        ).fetchone()
        if row:
            result_row = dict(row)

    if not result_row and not finished_event and not planned_event:
        return {"error": f"Test '{test_id}' not found in run '{run_id}'"}

    outcome = result_row["outcome"] if result_row else (
        finished_event["payload"]["outcome"] if finished_event else (
            "SKIPPED" if planned_event and planned_event["payload"]["action"] == "SKIPPED" else "UNKNOWN"
        )
    )

    steps_executed = [
        e["payload"] for e in events
        if e["type"] == "step.executed"
    ]
    diffs = [
        e["payload"] for e in events
        if e["type"] == "observation.diffed"
    ]

    # Synthesize human-readable explanation
    explanation_summary = ""
    reason = result_row.get("reason") if result_row else ""
    drift_detail = json.loads(result_row["drift_detail"]) if result_row and result_row.get("drift_detail") else {}

    if outcome == "PASS":
        explanation_summary = "All steps executed cleanly and all expectations evaluated true with no breaking diffs."
    elif outcome == "FAIL":
        if drift_detail and drift_detail.get("breaking_paths"):
            explanation_summary = (
                f"Defect candidate: One or more evaluable expectations evaluated false. "
                f"Compound drift also present on paths: {drift_detail['breaking_paths']}."
            )
        else:
            explanation_summary = "Defect candidate: One or more evaluable expectations evaluated false."
    elif outcome == "DRIFT":
        breaking = drift_detail.get("breaking_paths", []) if drift_detail else []
        if breaking:
            explanation_summary = (
                f"System contract drifted: Breaking observation changes detected on paths {breaking}. "
                f"Asserted expectations reading these paths became unevaluable."
            )
        else:
            explanation_summary = f"System contract drifted: {reason or 'pre-fingerprint or expectation mismatch'}"
    elif outcome == "ERROR":
        strict_explanations = {
            "unapproved": "Strict mode verification failed: Test has not been approved with an OpenSSH signature.",
            "missing-trace": "Strict mode verification failed: Recorded trace is missing.",
            "tampered": "Strict mode verification failed: Content hash mismatch against covered files in approval.",
            "bad-signature": "Strict mode verification failed: OpenSSH cryptographic signature is mathematically invalid.",
            "unknown-signer": "Strict mode verification failed: Approver key is not recognized by the trust root (CAIRN_ALLOWED_SIGNERS).",
            "env-mismatch": "Strict mode verification failed: Active environment profile does not match approval/trace.",
        }
        explanation_summary = strict_explanations.get(
            reason, f"Execution error: {reason or 'step transport failure or verification failure'}."
        )
    elif outcome == "SKIPPED":
        plan_reason = planned_event["payload"].get("reason") if planned_event else reason
        explanation_summary = f"Test was not executed: {plan_reason}."

    return {
        "run_id": run_id,
        "test_id": test_id,
        "outcome": outcome,
        "duration_ms": result_row.get("duration_ms", 0.0) if result_row else 0.0,
        "explanation": explanation_summary,
        "reason": reason,
        "drift_detail": drift_detail,
        "steps": steps_executed,
        "diffs": diffs,
        "versions": json.loads(result_row["versions"]) if result_row and result_row.get("versions") else {},
        "recorded_at": result_row.get("recorded_at") if result_row else None,
    }
