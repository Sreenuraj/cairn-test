"""
Tests for expectation evaluator (T1.5, FR-C13, FR-C14).
"""

from typing import Any
from cairn_test.contracts import (
    DiffChange,
    DiffKind,
    ObservationDiff,
    RunContext,
    StepResult,
)
from cairn_test.core.expectations import evaluate_expectation, paths_match

class DummyAssertion:
    name = "dummy"
    def __init__(self, reads_paths: list[str], eval_return: Any):
        self._reads = reads_paths
        self._eval_return = eval_return

    def reads(self, spec: dict) -> list[str]:
        return self._reads

    def evaluate(self, spec: dict, result: StepResult, ctx: RunContext) -> Any:
        return self._eval_return

def test_paths_match():
    assert paths_match("$.total", "$.total")
    assert paths_match("total", "$.total")
    assert paths_match("$.customer.id", "$.customer")
    assert paths_match("$.customer", "$.customer.id")
    assert not paths_match("$.total", "$.status")

def test_evaluate_rule_1_blocked():
    ctx = RunContext(run_id="run-1", worker_id="w-1", env_profile="local")
    exp = evaluate_expectation(
        exp_spec={"jsonpath": "$.status", "equals": "PLACED"},
        exp_id="e1",
        step_id="step2",
        assertion_type=DummyAssertion(["$.status"], True),
        step_result=None,
        obs_diff=None,
        blocked_by="step1",
        blocking_cause="DRIFT",
        ctx=ctx,
    )
    assert exp.value == "unevaluable"
    assert exp.reason == "blocked-by:step1"
    assert exp.blocking_cause == "DRIFT"

def test_evaluate_rule_2_breaking_diff():
    ctx = RunContext(run_id="run-1", worker_id="w-1", env_profile="local")
    diff = ObservationDiff(changes=[
        DiffChange(path="$.total", kind=DiffKind.BREAKING, recorded="number", observed=None)
    ])
    exp = evaluate_expectation(
        exp_spec={"jsonpath": "$.total", "equals": 49.98},
        exp_id="e2",
        step_id="step1",
        assertion_type=DummyAssertion(["$.total"], "missing"),
        step_result=StepResult(step_id="step1", status_code=200),
        obs_diff=diff,
        blocked_by=None,
        blocking_cause=None,
        ctx=ctx,
    )
    assert exp.value == "unevaluable"
    assert exp.reason == "breaking-diff:$.total"

def test_evaluate_rule_3_missing_without_diff():
    """A missing field without diff entry to explain it must evaluate to false (plan.md 6.2 rule 3)."""
    ctx = RunContext(run_id="run-1", worker_id="w-1", env_profile="local")
    no_diff = ObservationDiff(changes=[])
    exp = evaluate_expectation(
        exp_spec={"jsonpath": "$.user.email", "equals": "test@example.com"},
        exp_id="e3",
        step_id="step1",
        assertion_type=DummyAssertion(["$.user.email"], "missing"),
        step_result=StepResult(step_id="step1", status_code=200),
        obs_diff=no_diff,
        blocked_by=None,
        blocking_cause=None,
        ctx=ctx,
    )
    assert exp.value == "false"

def test_evaluate_rule_3_true_and_false():
    ctx = RunContext(run_id="run-1", worker_id="w-1", env_profile="local")
    res = StepResult(step_id="step1", status_code=200)

    # True
    exp_true = evaluate_expectation(
        exp_spec={"status": 200},
        exp_id="e4",
        step_id="step1",
        assertion_type=DummyAssertion(["$.status"], True),
        step_result=res,
        obs_diff=None,
        blocked_by=None,
        blocking_cause=None,
        ctx=ctx,
    )
    assert exp_true.value == "true"

    # False
    exp_false = evaluate_expectation(
        exp_spec={"status": 200},
        exp_id="e5",
        step_id="step1",
        assertion_type=DummyAssertion(["$.status"], False),
        step_result=res,
        obs_diff=None,
        blocked_by=None,
        blocking_cause=None,
        ctx=ctx,
    )
    assert exp_false.value == "false"

if __name__ == "__main__":
    test_paths_match()
    test_evaluate_rule_1_blocked()
    test_evaluate_rule_2_breaking_diff()
    test_evaluate_rule_3_missing_without_diff()
    test_evaluate_rule_3_true_and_false()
    print("All T1.5 expectation evaluator tests passed!")
