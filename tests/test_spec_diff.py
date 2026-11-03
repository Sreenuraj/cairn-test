"""
Test for T4.1: Verifies the OpenAPI request-side spec-diff classifier against the T0.5 fixtures in fixtures/api_diff_rules.yaml.
"""

from pathlib import Path
import yaml

from cairn_test.plugins.api.spec_diff import (
    classify_operation_diff,
    RepairMechanism,
    SpecChangeKind,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "fixtures" / "api_diff_rules.yaml"

def test_t05_request_side_spec_diff_fixtures():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    request_rules = data.get("request_rules", [])
    assert len(request_rules) == 9, f"Expected 9 request rules, got {len(request_rules)}"

    for case in request_rules:
        case_id = case["id"]
        exp_class = case["expected_class"]
        exp_mechanism = case["expected_mechanism"]
        rec_spec = case["recorded_spec"]
        obs_spec = case["observed_spec"]

        changes = classify_operation_diff(rec_spec, obs_spec)
        assert len(changes) > 0, f"No changes detected for rule '{case_id}'"

        primary_change = changes[0]
        assert primary_change.kind.value == exp_class, (
            f"Rule '{case_id}': expected class '{exp_class}', got '{primary_change.kind.value}'"
        )
        assert primary_change.mechanism.value == exp_mechanism, (
            f"Rule '{case_id}': expected mechanism '{exp_mechanism}', got '{primary_change.mechanism.value}'"
        )

if __name__ == "__main__":
    test_t05_request_side_spec_diff_fixtures()
    print("All T4.1 request-side spec diff fixtures passed!")
