"""
Expectation evaluator for cairn-test core (T1.5, FR-C13, FR-C14).

Implements normative rules from plan.md section 6.2:
1. Blocked steps: expectation is unevaluable with cause 'blocked-by:<step>'.
2. Breaking observation diff on reads paths: expectation is unevaluable with diff reason.
3. Otherwise evaluated: true or false. A value missing with no diff entry to explain it is false, not unevaluable.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from cairn_test.contracts import (
    AssertionType,
    DiffKind,
    ObservationDiff,
    RunContext,
    StepResult,
)

@dataclass
class EvaluatedExpectation:
    expectation_id: str
    step_id: str
    kind: str
    value: str  # "true" | "false" | "unevaluable"
    reason: str | None = None
    blocking_cause: str | None = None  # "DRIFT" | "ERROR"

def paths_match(read_path: str, diff_path: str) -> bool:
    """
    Check if a read path is affected by a breaking diff path.
    Supports exact match, normalization of $. prefix, and ancestor/descendant relationships.
    """
    r = read_path.strip()
    d = diff_path.strip()
    if r == d:
        return True

    # Normalize leading "$." or "$"
    r_norm = r[2:] if r.startswith("$.") else (r[1:] if r.startswith("$") else r)
    d_norm = d[2:] if d.startswith("$.") else (d[1:] if d.startswith("$") else d)

    if r_norm == d_norm:
        return True

    # Check hierarchy: if breaking change is an ancestor (e.g. $.customer broken -> $.customer.id is unevaluable)
    # or child path of the read path
    if r_norm.startswith(d_norm + ".") or d_norm.startswith(r_norm + "."):
        return True

    return False

def evaluate_expectation(
    exp_spec: dict[str, Any],
    exp_id: str,
    step_id: str,
    assertion_type: AssertionType | None,
    step_result: StepResult | None,
    obs_diff: ObservationDiff | None,
    blocked_by: str | None,
    blocking_cause: str | None,
    ctx: RunContext,
) -> EvaluatedExpectation:
    kind = "custom"
    if "status" in exp_spec:
        kind = "status"
    elif "jsonpath" in exp_spec:
        kind = "jsonpath"
    elif "header" in exp_spec:
        kind = "header"
    elif "schema" in exp_spec:
        kind = "schema"
    elif "property" in exp_spec:
        kind = "property"
    elif "state" in exp_spec:
        kind = "state"

    # Rule 1: Step was blocked by an earlier step
    if blocked_by:
        return EvaluatedExpectation(
            expectation_id=exp_id,
            step_id=step_id,
            kind=kind,
            value="unevaluable",
            reason=f"blocked-by:{blocked_by}",
            blocking_cause=blocking_cause or "DRIFT",
        )

    # Transport error on step execution
    if step_result and step_result.transport_error:
        return EvaluatedExpectation(
            expectation_id=exp_id,
            step_id=step_id,
            kind=kind,
            value="unevaluable",
            reason=f"transport-error:{step_result.transport_error}",
            blocking_cause="ERROR",
        )

    # Determine paths read by this expectation
    reads_paths: list[str] = []
    if assertion_type:
        reads_paths = assertion_type.reads(exp_spec)
    else:
        # Static default reads derivation (plan.md 6.2)
        if "status" in exp_spec:
            reads_paths = ["$.status"]
        elif "jsonpath" in exp_spec:
            reads_paths = [exp_spec["jsonpath"]]
        elif "header" in exp_spec:
            h = exp_spec["header"]
            h_name = h if isinstance(h, str) else list(h.keys())[0]
            reads_paths = [f"headers.{h_name}"]

    # Rule 2: Breaking observation diff matches any read path
    if obs_diff and obs_diff.has_breaking:
        for change in obs_diff.changes:
            if change.kind == DiffKind.BREAKING:
                for rp in reads_paths:
                    if paths_match(rp, change.path):
                        # For status assertions: if the test expected a successful response (2xx), but the server
                        # returned a client error (4xx), the server rejected the recorded request format (contract
                        # change on request side: e.g. 404 path moved C-REQ-2, 400 new required parameter C-REQ-4).
                        # This makes the 2xx status expectation unevaluable -> DRIFT.
                        # Conversely, if a negative test expected 4xx but got 2xx (e.g. BUG-2 validation regression),
                        # or if the server returned a 5xx error (defect), the expectation evaluates to false -> FAIL.
                        if rp == "$.status" and kind == "status":
                            observed_status = step_result.status_code if step_result else None
                            expected_status = exp_spec.get("status")
                            if expected_status and 200 <= int(expected_status) < 300:
                                if observed_status and 400 <= int(observed_status) < 500:
                                    pass
                                else:
                                    continue
                            else:
                                continue
                        return EvaluatedExpectation(
                            expectation_id=exp_id,
                            step_id=step_id,
                            kind=kind,
                            value="unevaluable",
                            reason=f"breaking-diff:{change.path}",
                        )

    # Rule 3: Evaluate true or false
    if assertion_type and step_result:
        raw_res = assertion_type.evaluate(exp_spec, step_result, ctx)
        if raw_res is True or raw_res == "true":
            val = "true"
        else:
            # Value missing with no diff entry is false (plan.md 6.2 rule 3)
            val = "false"
        return EvaluatedExpectation(
            expectation_id=exp_id,
            step_id=step_id,
            kind=kind,
            value=val,
        )

    # Default if no assertion handler provided
    return EvaluatedExpectation(
        expectation_id=exp_id,
        step_id=step_id,
        kind=kind,
        value="true",
    )
