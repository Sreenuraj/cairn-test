"""
Verification test for T1.6: runs the outcome engine against the T0.4 decision table oracle fixture.
"""

from pathlib import Path
from typing import Any
import yaml
from cairn_test.contracts import DiffChange, DiffKind, ObservationDiff, RunContext, StepResult
from cairn_test.core.expectations import EvaluatedExpectation, evaluate_expectation
from cairn_test.core.outcome import decide_outcome

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "fixtures" / "outcome_decision_table.yaml"

class FixtureAssertion:
    name = "fixture"
    def __init__(self, reads_paths: list[str], raw_eval: str):
        self._reads = reads_paths
        self._raw_eval = raw_eval

    def reads(self, spec: dict) -> list[str]:
        return self._reads

    def evaluate(self, spec: dict, result: StepResult, ctx: RunContext) -> Any:
        if self._raw_eval == "true":
            return True
        elif self._raw_eval == "false":
            return False
        return "missing"

def test_t04_decision_table_oracle():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        fixture_data = yaml.safe_load(f)

    rows = fixture_data.get("rows", [])
    assert len(rows) > 0, "No rows found in outcome_decision_table.yaml"

    ctx = RunContext(run_id="oracle-run", worker_id="w-0", env_profile="local")

    for row in rows:
        row_id = row["id"]
        inputs = row["inputs"]
        expected = row["expected"]

        planned = inputs.get("planned", "EXECUTE")
        skip_reason = inputs.get("skip_reason")
        verification = inputs.get("verification", "valid")

        steps_inputs = inputs.get("steps", [])
        expectations_inputs = inputs.get("expectations", [])

        # Evaluate expectations using the expectations engine
        evaluated_exps: list[EvaluatedExpectation] = []
        for exp_in in expectations_inputs:
            exp_id = exp_in["id"]
            step_id = exp_in["step_id"]
            reads = exp_in.get("reads", [])
            raw_eval = exp_in.get("raw_eval", "true")

            # Find matching step
            st = next((s for s in steps_inputs if s["id"] == step_id), None)
            step_res = None
            obs_diff = None
            blocked_by = None

            if st:
                blocked_by = st.get("blocked_by")
                t_err = st.get("transport_error")
                step_res = StepResult(step_id=step_id, status_code=200 if not t_err else None, transport_error=t_err)
                diff_data = st.get("observation_diff", {})
                changes = []
                for p in diff_data.get("breaking_paths", []):
                    changes.append(DiffChange(path=p, kind=DiffKind.BREAKING, recorded="val", observed="broken"))
                for p in diff_data.get("additive_paths", []):
                    changes.append(DiffChange(path=p, kind=DiffKind.ADDITIVE, recorded=None, observed="new"))
                obs_diff = ObservationDiff(changes=changes)

            # Determine blocking cause
            blocking_cause = None
            if blocked_by:
                b_step = next((s for s in steps_inputs if s["id"] == blocked_by), None)
                if b_step and b_step.get("transport_error"):
                    blocking_cause = "ERROR"
                else:
                    blocking_cause = "DRIFT"

            evaluated = evaluate_expectation(
                exp_spec={"custom": True},
                exp_id=exp_id,
                step_id=step_id,
                assertion_type=FixtureAssertion(reads, raw_eval),
                step_result=step_res,
                obs_diff=obs_diff,
                blocked_by=blocked_by,
                blocking_cause=blocking_cause,
                ctx=ctx,
            )
            evaluated_exps.append(evaluated)

        # Run outcome engine
        verdict = decide_outcome(
            planned=planned,
            skip_reason=skip_reason,
            verification=verification,
            steps_info=steps_inputs,
            expectations=evaluated_exps,
        )

        # Assert outcome
        assert verdict.outcome == expected["outcome"], (
            f"Row '{row_id}' failed: expected outcome {expected['outcome']}, got {verdict.outcome}"
        )

        # Assert drift detail
        if "has_drift_detail" in expected:
            assert verdict.has_drift_detail == expected["has_drift_detail"], (
                f"Row '{row_id}' failed: expected has_drift_detail {expected['has_drift_detail']}, got {verdict.has_drift_detail}"
            )

        # Assert expected expectation values if defined
        if "expectations" in expected:
            for exp_exp in expected["expectations"]:
                actual_exp = next((e for e in evaluated_exps if e.expectation_id == exp_exp["id"]), None)
                assert actual_exp is not None, f"Row '{row_id}': expectation '{exp_exp['id']}' missing"
                assert actual_exp.value == exp_exp["value"], (
                    f"Row '{row_id}' exp '{exp_exp['id']}': expected value {exp_exp['value']}, got {actual_exp.value}"
                )

        print(f"Row '{row_id}': PASSED (outcome={verdict.outcome})")

    print(f"\nAll {len(rows)} rows from T0.4 decision table oracle passed completely!")

if __name__ == "__main__":
    from typing import Any
    test_t04_decision_table_oracle()
