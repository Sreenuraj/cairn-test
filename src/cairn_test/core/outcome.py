"""
Outcome engine for cairn-test core (T1.6, FR-C5, FR-C6).

Precedence (normative):
ERROR > FAIL > DRIFT > PASS

Invariants:
- Only the outcome engine assigns outcomes.
- Lower findings (e.g. drift when FAIL wins) are retained and reported as detail.
- Evaluates against the T0.4 decision table oracle.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from cairn_test.contracts import DiffKind, ObservationDiff, StepResult
from cairn_test.core.expectations import EvaluatedExpectation

class OutcomeEnum(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    DRIFT = "DRIFT"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"

@dataclass
class TestVerdict:
    outcome: str
    reason: str | None = None
    expectations: list[EvaluatedExpectation] = field(default_factory=list)
    has_drift_detail: bool = False
    drift_detail: dict[str, Any] | None = None

def decide_outcome(
    planned: str = "EXECUTE",
    skip_reason: str | None = None,
    verification: str = "valid",
    verification_reason: str | None = None,
    steps_info: list[dict[str, Any]] | None = None,
    expectations: list[EvaluatedExpectation] | None = None,
) -> TestVerdict:
    exps = expectations or []
    steps = steps_info or []

    # 1. Planning stage (SKIPPED)
    if planned == "SKIPPED":
        return TestVerdict(
            outcome=OutcomeEnum.SKIPPED.value,
            reason=skip_reason or "skipped",
            expectations=exps,
        )

    # 2. Strict verification failure (ERROR)
    if verification != "valid":
        return TestVerdict(
            outcome=OutcomeEnum.ERROR.value,
            reason=verification_reason or verification,
            expectations=exps,
        )

    # Gather drift and error indicators
    has_transport_error = False
    transport_err_msg = None
    has_blocked_by_error = False

    breaking_diff_paths: list[str] = []
    has_pre_fingerprint_mismatch = False
    has_unevaluable_exp = False
    has_blocked_by_drift = False

    for s in steps:
        t_err = s.get("transport_error")
        if t_err:
            has_transport_error = True
            transport_err_msg = t_err

        if not s.get("pre_fingerprint_match", True):
            has_pre_fingerprint_mismatch = True

        obs_diff = s.get("observation_diff", {})
        breaking = obs_diff.get("breaking_paths", [])
        if breaking:
            breaking_diff_paths.extend(breaking)

    for exp in exps:
        if exp.value == "unevaluable":
            has_unevaluable_exp = True
            if exp.blocking_cause == "ERROR":
                has_blocked_by_error = True
            elif exp.blocking_cause == "DRIFT":
                has_blocked_by_drift = True

    # 3. Execution / Transport ERROR (precedence: ERROR)
    if has_transport_error or has_blocked_by_error:
        reason = transport_err_msg or "step-blocked-by-error"
        return TestVerdict(
            outcome=OutcomeEnum.ERROR.value,
            reason=reason,
            expectations=exps,
            has_drift_detail=False,
        )

    # Check for any FALSE expectation (FAIL)
    has_false_exp = any(exp.value == "false" for exp in exps)

    # Check for DRIFT condition
    is_drift = (
        bool(breaking_diff_paths)
        or has_pre_fingerprint_mismatch
        or has_unevaluable_exp
        or has_blocked_by_drift
    )

    drift_detail = None
    if is_drift:
        drift_detail = {
            "breaking_paths": breaking_diff_paths,
            "pre_fingerprint_mismatch": has_pre_fingerprint_mismatch,
            "unevaluable_expectations": [e.expectation_id for e in exps if e.value == "unevaluable"],
        }

    # 4. FAIL (precedence: FAIL > DRIFT)
    if has_false_exp:
        return TestVerdict(
            outcome=OutcomeEnum.FAIL.value,
            expectations=exps,
            has_drift_detail=is_drift,
            drift_detail=drift_detail,
        )

    # 5. DRIFT
    if is_drift:
        return TestVerdict(
            outcome=OutcomeEnum.DRIFT.value,
            expectations=exps,
            has_drift_detail=True,
            drift_detail=drift_detail,
        )

    # 6. PASS
    return TestVerdict(
        outcome=OutcomeEnum.PASS.value,
        expectations=exps,
        has_drift_detail=False,
    )
