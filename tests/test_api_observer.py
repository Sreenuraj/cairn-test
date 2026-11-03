"""
Verification tests for API Observer passing T0.5 fixtures (T2.5, FR-A4, FR-A5, FR-C15).
"""

from pathlib import Path
import yaml
from cairn_test.contracts import DiffKind, Observation
from cairn_test.plugins.api.observer import ApiObserver, normalize_body_shape

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "fixtures" / "api_diff_rules.yaml"

def test_t05_response_diff_fixtures():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        fixture_data = yaml.safe_load(f)

    rules = fixture_data.get("response_rules", [])
    assert len(rules) > 0, "No response_rules found in api_diff_rules.yaml"

    observer = ApiObserver()

    for r in rules:
        rule_id = r["id"]
        expected_class = r["expected_class"]
        rec_data = r["recorded"]
        obs_data = r["observed"]
        expected_changes = r.get("expected_changes", [])

        rec_obs = Observation(
            status=rec_data["status"],
            headers=rec_data.get("headers", []),
            body_shape=rec_data.get("body_shape"),
        )
        observed_obs = Observation(
            status=obs_data["status"],
            headers=obs_data.get("headers", []),
            body_shape=obs_data.get("body_shape"),
        )

        diff = observer.compare(rec_obs, observed_obs)

        if expected_class == "identical":
            assert not diff.has_breaking, f"Rule '{rule_id}' expected identical, got breaking"
            assert not diff.has_additive, f"Rule '{rule_id}' expected identical, got additive"
            assert len(diff.changes) == 0, f"Rule '{rule_id}' expected 0 changes, got {diff.changes}"
        elif expected_class == "additive":
            assert diff.has_additive, f"Rule '{rule_id}' expected additive changes"
            assert not diff.has_breaking, f"Rule '{rule_id}' expected no breaking changes"
        elif expected_class == "breaking":
            assert diff.has_breaking, f"Rule '{rule_id}' expected breaking changes"

        # Check expected paths if given
        for exp_c in expected_changes:
            exp_path = exp_c["path"]
            exp_kind = exp_c["kind"]
            matching = [c for c in diff.changes if c.path == exp_path and c.kind.value == exp_kind]
            assert len(matching) > 0, f"Rule '{rule_id}': change for path '{exp_path}' of kind '{exp_kind}' not found in {diff.changes}"

        print(f"Response diff rule '{rule_id}': PASSED ({expected_class})")

    print(f"\nAll {len(rules)} T0.5 response diff rules passed completely!")

if __name__ == "__main__":
    test_t05_response_diff_fixtures()

