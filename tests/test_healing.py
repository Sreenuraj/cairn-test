"""
Comprehensive tests for Phase 4: Healing, Impact Analysis, Value Requests,
Expectation Change Suggestions, and Heal-Limit Enforcement (T4.1..T4.6, T4.8).
"""

from pathlib import Path
import tempfile
import yaml

from cairn_test.core.healing import (
    ImpactAnalyzer,
    HealEngine,
    accept_observations_batch,
    dry_run_expectations,
)
from cairn_test.plugins.api.spec_diff import (
    RepairMechanism,
    SpecChange,
    SpecChangeKind,
    SpecDiffClassifier,
)
from cairn_test.core.schemas import load_yaml, validate_document

REPO_ROOT = Path(__file__).resolve().parent.parent

def test_impact_analysis_declared_and_step_ops():
    """T4.2: Tests mapping tests to touched operations including declared touches."""
    old_spec = {
        "openapi": "3.0.0",
        "paths": {
            "/orders": {
                "post": {
                    "operationId": "createOrder",
                    "parameters": [],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["items"],
                                    "properties": {"items": {"type": "array"}},
                                }
                            }
                        }
                    },
                }
            },
            "/products": {
                "get": {
                    "operationId": "getProducts",
                    "parameters": [],
                }
            },
        },
    }

    new_spec = {
        "openapi": "3.0.0",
        "paths": {
            "/v2/orders": {
                "post": {
                    "operationId": "createOrder",
                    "parameters": [],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["items"],
                                    "properties": {"items": {"type": "array"}},
                                }
                            }
                        }
                    },
                }
            },
            "/products": {
                "get": {
                    "operationId": "getProducts",
                    "parameters": [],
                }
            },
        },
    }

    tests = [
        {
            "id": "test_order_step",
            "steps": [{"op": "createOrder"}],
        },
        {
            "id": "test_order_declared_touch",
            "touches": ["createOrder"],
            "steps": [{"op": "someCustomStep"}],
        },
        {
            "id": "test_unaffected_product",
            "steps": [{"op": "getProducts"}],
        },
    ]

    analyzer = ImpactAnalyzer(SpecDiffClassifier())
    affected = analyzer.find_affected_tests(tests, old_spec, new_spec)

    affected_ids = [a["test_id"] for a in affected]
    assert "test_order_step" in affected_ids, "Test with step op should be affected"
    assert "test_order_declared_touch" in affected_ids, "Test with declared touches should be affected"
    assert "test_unaffected_product" not in affected_ids, "Unaffected test should not be affected"
    print("Impact analysis (T4.2) verified.")

def test_heal_proposal_generation_and_dry_run():
    """T4.3: Heal proposals for healable fields with dry-run expectation checks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        healer = HealEngine()

        test_def = {
            "schema": "cairn-test.test/v1",
            "id": "create_order_test",
            "steps": [
                {"id": "step_0", "op": "createOrder", "plugin": "api", "args": {"items": ["sku_1"]}}
            ],
            "expect": [
                {"status": 201},
                {"jsonpath": "$.status", "equals": "PENDING"},
            ],
        }

        recorded_trace = {
            "schema": "cairn-test.trace/v1",
            "test": "create_order_test",
            "steps": [
                {
                    "id": "step_0",
                    "resolved": {
                        "operation": "createOrder",
                        "method": "POST",
                        "path": "/orders",
                    },
                    "observation": {
                        "status": 201,
                        "headers": {"content-type": "application/json"},
                        "body": {"id": "ord_123", "status": "PENDING"},
                    },
                }
            ],
        }

        # 1. Path changed (/orders -> /v2/orders)
        change = SpecChange(
            kind=SpecChangeKind.BREAKING,
            mechanism=RepairMechanism.HEAL,
            rule_id="path_changed_same_op",
            detail="Path changed from /orders to /v2/orders",
            operation="createOrder",
            old_value="/orders",
            new_value="/v2/orders",
        )

        proposal = healer.generate_heal_proposal(
            test_id="create_order_test",
            test_def=test_def,
            recorded_trace=recorded_trace,
            spec_change=change,
            repo_root=repo_root,
        )

        assert proposal is not None
        assert proposal["kind"] == "heal"
        validate_document(proposal, "proposal.v1")

        # Verify proposal details
        details = proposal["details"]
        assert details["old_resolved"]["path"] == "/orders"
        assert details["new_resolved"]["path"] == "/v2/orders"
        assert details["dry_run"]["exp_0"] == "true"
        assert details["dry_run"]["exp_1"] == "true"

        # Check files written in proposals/
        prop_file = repo_root / "proposals" / "create_order_test.heal.yaml"
        draft_trace_file = repo_root / "proposals" / "create_order_test.trace.yaml"
        assert prop_file.is_file(), "Heal proposal YAML must exist"
        assert draft_trace_file.is_file(), "Draft trace YAML must exist"

        # 2. Method changed (PUT -> PATCH)
        change_method = SpecChange(
            kind=SpecChangeKind.BREAKING,
            mechanism=RepairMechanism.HEAL,
            rule_id="method_changed_same_op",
            detail="Method changed from PUT to PATCH",
            operation="createOrder",
            old_value="PUT",
            new_value="PATCH",
        )
        prop_method = healer.generate_heal_proposal(
            test_id="create_order_test",
            test_def=test_def,
            recorded_trace=recorded_trace,
            spec_change=change_method,
            repo_root=repo_root,
        )
        assert prop_method is not None
        assert prop_method["details"]["new_resolved"]["method"] == "PATCH"

        # 3. OperationId renamed (createOrder -> createOrderV2)
        change_renamed = SpecChange(
            kind=SpecChangeKind.BREAKING,
            mechanism=RepairMechanism.HEAL,
            rule_id="operation_renamed",
            detail="OperationId renamed from createOrder to createOrderV2",
            operation="createOrder",
            old_value="createOrder",
            new_value="createOrderV2",
        )
        prop_renamed = healer.generate_heal_proposal(
            test_id="create_order_test",
            test_def=test_def,
            recorded_trace=recorded_trace,
            spec_change=change_renamed,
            repo_root=repo_root,
        )
        assert prop_renamed is not None
        assert prop_renamed["details"]["new_resolved"]["operation"] == "createOrderV2"

        print("Heal proposal generation and dry run (T4.3) verified.")

def test_value_request_and_expectation_suggestions():
    """T4.4: Value requests (no synthetic values) and expectation suggestions (JSONPath-only rewrite)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        healer = HealEngine()

        test_def = {
            "schema": "cairn-test.test/v1",
            "id": "b07_get_order",
            "steps": [{"op": "getOrder"}],
            "expect": [
                {"status": 200},
                {"jsonpath": "$.total", "equals": 100},
            ],
        }

        # 1. Value request for new required input
        val_change = SpecChange(
            kind=SpecChangeKind.BREAKING,
            mechanism=RepairMechanism.VALUE_REQUEST,
            rule_id="param_required_added",
            detail="New required body field: payment_method",
            operation="createOrder",
            new_value="payment_method",
        )

        val_proposal = healer.generate_value_request(
            test_id="create_order_test",
            spec_change=val_change,
            repo_root=repo_root,
        )
        assert val_proposal is not None
        assert val_proposal["kind"] == "value-request"
        assert val_proposal["details"]["param_name"] == "payment_method"
        validate_document(val_proposal, "proposal.v1")

        # 2. Expectation suggestion with exactly 1 candidate: JSONPath rewrite
        exp_prop = healer.generate_expectation_change_suggestion(
            test_id="b07_get_order",
            test_def=test_def,
            old_path="$.total",
            candidates=["$.grand_total"],
            repo_root=repo_root,
        )
        assert exp_prop is not None
        assert exp_prop["kind"] == "expectation-change"
        assert exp_prop["details"]["old_path"] == "$.total"
        assert exp_prop["details"]["suggested_path"] == "$.grand_total"
        assert "Suggested JSONPath rewrite" in exp_prop["reason"]
        validate_document(exp_prop, "proposal.v1")

        # 3. Expectation change request with 0 candidates: NO suggested_path
        exp_prop_none = healer.generate_expectation_change_suggestion(
            test_id="b07_get_order",
            test_def=test_def,
            old_path="$.total",
            candidates=[],
            repo_root=repo_root,
        )
        assert exp_prop_none is not None
        assert "suggested_path" not in exp_prop_none["details"]
        assert "unambiguous candidate not found" in exp_prop_none["reason"]
        validate_document(exp_prop_none, "proposal.v1")

        # 4. Expectation change request with >1 candidates (ambiguous): NO suggested_path
        exp_prop_ambig = healer.generate_expectation_change_suggestion(
            test_id="b07_get_order",
            test_def=test_def,
            old_path="$.total",
            candidates=["$.grand_total", "$.subtotal"],
            repo_root=repo_root,
        )
        assert exp_prop_ambig is not None
        assert "suggested_path" not in exp_prop_ambig["details"]
        assert len(exp_prop_ambig["details"]["candidates"]) == 2
        validate_document(exp_prop_ambig, "proposal.v1")

        print("Value requests and expectation suggestions (T4.4) verified.")

def test_heal_limit_enforcement_zero_false_heals_zero_masking():
    """
    T4.5 / FR-R7: An automated test tries to make the healer:
    1. Heal a test that had outcome FAIL
    2. Suggest an expectation change for a FAIL (zero masking suggestions)
    3. Modify an expectation, data value, arg, or test file directly
    Engine refuses each attempt.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        healer = HealEngine()

        test_def = {
            "schema": "cairn-test.test/v1",
            "id": "b01_failing_behavior",
            "steps": [{"op": "createOrder"}],
            "expect": [{"status": 201}],
        }
        trace = {
            "schema": "cairn-test.trace/v1",
            "test": "b01_failing_behavior",
            "steps": [
                {
                    "id": "step_0",
                    "resolved": {"operation": "createOrder", "path": "/orders"},
                    "observation": {"status": 500},
                }
            ],
        }
        change = SpecChange(
            kind=SpecChangeKind.BREAKING,
            mechanism=RepairMechanism.HEAL,
            rule_id="path_changed_same_op",
            detail="Path changed",
            operation="createOrder",
            old_value="/orders",
            new_value="/v2/orders",
        )

        # 1. Refusal to heal a FAIL
        prop_fail = healer.generate_heal_proposal(
            test_id="b01_failing_behavior",
            test_def=test_def,
            recorded_trace=trace,
            spec_change=change,
            repo_root=repo_root,
            test_outcome="FAIL",
        )
        assert prop_fail is None, "Engine must refuse to heal a FAIL outcome (zero false heals)"

        # 2. Refusal to suggest expectation change for a FAIL (zero masking suggestions)
        sugg_fail = healer.generate_expectation_change_suggestion(
            test_id="b01_failing_behavior",
            test_def=test_def,
            old_path="$.total",
            candidates=["$.grand_total"],
            repo_root=repo_root,
            test_outcome="FAIL",
        )
        assert sugg_fail is None, "Engine must refuse to suggest expectation changes on FAIL (zero masking suggestions)"

        # 3. Refusal to heal non-healable fields (expectations, data, args, test files)
        for non_healable in ["expectations", "data", "args", "test_file", "recorded_observation"]:
            try:
                healer.refuse_invalid_healing(non_healable)
                assert False, f"Engine should have refused healing for '{non_healable}'"
            except ValueError as e:
                assert "is not healable" in str(e)

        print("Heal-limit enforcement (T4.5 / FR-R7) verified.")

def test_accept_observations_batch():
    """T4.6: accept-observations generates batch proposals for additive diffs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        observed_traces = {
            "b01_test": {
                "schema": "cairn-test.trace/v1",
                "test": "b01_test",
                "steps": [
                    {
                        "id": "step_0",
                        "observation": {
                            "status": 200,
                            "body": {"id": "1", "name": "item", "new_opt_field": "added"},
                        },
                    }
                ],
            }
        }
        recorded_traces = {
            "b01_test": {
                "schema": "cairn-test.trace/v1",
                "test": "b01_test",
                "steps": [
                    {
                        "id": "step_0",
                        "observation": {
                            "status": 200,
                            "body": {"id": "1", "name": "item"},
                        },
                    }
                ],
            }
        }

        props = accept_observations_batch(repo_root, observed_traces, recorded_traces)
        assert len(props) == 1
        assert props[0].is_file()

        prop_data = load_yaml(props[0])
        assert prop_data["kind"] == "observation-update"
        assert prop_data["test"] == "b01_test"
        validate_document(prop_data, "proposal.v1")

        draft_tr = repo_root / "proposals" / "b01_test.trace.yaml"
        assert draft_tr.is_file(), "Draft trace file must be created in proposals/"

        print("accept-observations batch (T4.6) verified.")

if __name__ == "__main__":
    test_impact_analysis_declared_and_step_ops()
    test_heal_proposal_generation_and_dry_run()
    test_value_request_and_expectation_suggestions()
    test_heal_limit_enforcement_zero_false_heals_zero_masking()
    test_accept_observations_batch()
    print("\nAll Phase 4 Healing & Impact tests passed successfully!")

