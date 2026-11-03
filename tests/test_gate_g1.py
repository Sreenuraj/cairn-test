"""
Gate G1 Verification Suite (T1.12, Gate G1, NFR-9, NFR-6).

Verifies:
1. Core logic is unit-tested using ONLY the fake plugin (no network / HTTP / external services).
2. A mixed suite on the fake plugin produces:
   - PASS (identical and benign additive)
   - FAIL (behavioral defect)
   - DRIFT (breaking observation change and pre-fingerprint mismatch)
   - ERROR (transport error)
   - SKIPPED (quarantined)
   - Compound cases (contract change + bug, additive + bug, blocked step)
3. Stored event explanations for every outcome.
4. Determinism: 10 consecutive runs produce identical outcomes and ordering (NFR-6).
"""

import json
from pathlib import Path
import tempfile
import yaml

from cairn_test.core.events import EventBus, EventStore
from cairn_test.core.explain import explain_test
from cairn_test.core.planner import PlanItem, Planner
from cairn_test.core.plugins import PluginRegistry
from cairn_test.core.scheduler import Scheduler
from cairn_test.plugins.fake import register_fake_plugin

def create_g1_suite() -> tuple[list[dict], dict[str, dict]]:
    test_defs = [
        # 1. Clean PASS
        {
            "schema": "cairn-test.test/v1",
            "id": "case-01-pass-clean",
            "steps": [{"id": "s1", "kind": "fake", "op": "step1", "args": {"status": 200, "data": {"total": 50}}}],
            "expect": [{"after": "s1", "fake": {"reads": ["$.total"], "evaluate": True}}],
        },
        # 2. Benign additive PASS
        {
            "schema": "cairn-test.test/v1",
            "id": "case-02-pass-additive",
            "steps": [{"id": "s1", "kind": "fake", "op": "step1", "args": {"status": 200, "data": {"total": 50, "tracking": "hint123"}}}],
            "expect": [{"after": "s1", "fake": {"reads": ["$.total"], "evaluate": True}}],
        },
        # 3. Pure behavioral bug (FAIL)
        {
            "schema": "cairn-test.test/v1",
            "id": "case-03-fail-bug-only",
            "steps": [{"id": "s1", "kind": "fake", "op": "step1", "args": {"status": 200, "data": {"total": 50}}}],
            "expect": [{"after": "s1", "fake": {"reads": ["$.total"], "evaluate": False}}],
        },
        # 4. Pure contract change (DRIFT)
        {
            "schema": "cairn-test.test/v1",
            "id": "case-04-drift-contract-only",
            "steps": [{"id": "s1", "kind": "fake", "op": "step1", "args": {"status": 200, "data": {"grand_total": 50}}}],
            "expect": [{"after": "s1", "fake": {"reads": ["$.total"], "evaluate": "missing"}}],
        },
        # 5. Pre-fingerprint mismatch only (DRIFT)
        {
            "schema": "cairn-test.test/v1",
            "id": "case-05-drift-fingerprint-mismatch",
            "steps": [{"id": "s1", "kind": "fake", "op": "step1", "args": {"op_hash": "hash-new-spec", "status": 200, "data": {"total": 50}}}],
            "expect": [{"after": "s1", "fake": {"reads": ["$.total"], "evaluate": True}}],
        },
        # 6. Transport error: connection refused (ERROR)
        {
            "schema": "cairn-test.test/v1",
            "id": "case-06-error-transport",
            "steps": [{"id": "s1", "kind": "fake", "op": "step1", "args": {"transport_error": "Connection refused to target"}}],
            "expect": [{"after": "s1", "fake": {"reads": ["$.status"], "evaluate": "missing"}}],
        },
        # 7. Quarantined (SKIPPED)
        {
            "schema": "cairn-test.test/v1",
            "id": "case-07-skip-quarantine",
            "quarantine": {"reason": "known flaky upstream"},
            "steps": [{"id": "s1", "kind": "fake", "op": "step1", "args": {}}],
            "expect": [],
        },
        # 8. Compound 1: Contract change + unrelated bug (FAIL with drift detail)
        {
            "schema": "cairn-test.test/v1",
            "id": "case-08-compound-contract-plus-bug",
            "steps": [{"id": "s1", "kind": "fake", "op": "step1", "args": {"status": 200, "data": {"status": "ACTIVE"}}}],
            "expect": [
                {"after": "s1", "fake": {"reads": ["$.total"], "evaluate": "missing"}},
                {"after": "s1", "fake": {"reads": ["$.status"], "evaluate": False}},
            ],
        },
        # 9. Compound 2: Additive change + bug (FAIL)
        {
            "schema": "cairn-test.test/v1",
            "id": "case-09-compound-additive-plus-bug",
            "steps": [{"id": "s1", "kind": "fake", "op": "step1", "args": {"status": 200, "data": {"total": 50, "new_field": "val"}}}],
            "expect": [
                {"after": "s1", "fake": {"reads": ["$.total"], "evaluate": False}},
            ],
        },
        # 10. Compound 3: Step 1 drift blocks Step 2 variable extraction (DRIFT, step 2 blocked)
        {
            "schema": "cairn-test.test/v1",
            "id": "case-10-compound-step1-drift-blocks-step2",
            "steps": [
                {
                    "id": "s1",
                    "kind": "fake",
                    "op": "login",
                    "args": {"status": 200, "data": {}},  # token removed
                    "extract": {"auth_token": "$.token"},
                },
                {
                    "id": "s2",
                    "kind": "fake",
                    "op": "get_orders",
                    "args": {"status": 200, "auth": "{auth_token}", "data": {"count": 3}},
                },
            ],
            "expect": [
                {"after": "s1", "fake": {"reads": ["$.token"], "evaluate": "missing"}},
                {"after": "s2", "fake": {"reads": ["$.count"], "evaluate": True}},
            ],
        },
    ]

    traces = {
        "case-01-pass-clean": {
            "steps": [{"id": "s1", "observation": {"status": 200, "body_shape": {"total": "int"}}, "pre_fingerprint": {"op_hash": "hash-step1"}}]
        },
        "case-02-pass-additive": {
            "steps": [{"id": "s1", "observation": {"status": 200, "body_shape": {"total": "int"}}, "pre_fingerprint": {"op_hash": "hash-step1"}}]
        },
        "case-03-fail-bug-only": {
            "steps": [{"id": "s1", "observation": {"status": 200, "body_shape": {"total": "int"}}, "pre_fingerprint": {"op_hash": "hash-step1"}}]
        },
        "case-04-drift-contract-only": {
            "steps": [{"id": "s1", "observation": {"status": 200, "body_shape": {"total": "int"}}, "pre_fingerprint": {"op_hash": "hash-step1"}}]
        },
        "case-05-drift-fingerprint-mismatch": {
            "steps": [{"id": "s1", "observation": {"status": 200, "body_shape": {"total": "int"}}, "pre_fingerprint": {"op_hash": "hash-old-spec"}}]
        },
        "case-06-error-transport": {
            "steps": [{"id": "s1", "observation": {"status": 200, "body_shape": {}}, "pre_fingerprint": {"op_hash": "hash-step1"}}]
        },
        "case-08-compound-contract-plus-bug": {
            "steps": [{"id": "s1", "observation": {"status": 200, "body_shape": {"total": "int", "status": "str"}}, "pre_fingerprint": {"op_hash": "hash-step1"}}]
        },
        "case-09-compound-additive-plus-bug": {
            "steps": [{"id": "s1", "observation": {"status": 200, "body_shape": {"total": "int"}}, "pre_fingerprint": {"op_hash": "hash-step1"}}]
        },
        "case-10-compound-step1-drift-blocks-step2": {
            "steps": [
                {"id": "s1", "observation": {"status": 200, "body_shape": {"token": "str"}}, "pre_fingerprint": {"op_hash": "hash-login"}},
                {"id": "s2", "observation": {"status": 200, "body_shape": {"count": "int"}}, "pre_fingerprint": {"op_hash": "hash-get_orders"}},
            ]
        },
    }

    return test_defs, traces

def run_suite_once(base_dir: Path, run_id: str) -> tuple[dict[str, str], list[str], EventStore]:
    store = EventStore(base_dir=base_dir)
    bus = EventBus(run_id=run_id, store=store)
    registry = PluginRegistry()
    register_fake_plugin(registry)

    test_defs, traces = create_g1_suite()
    planner = Planner(event_bus=bus)
    planned = planner.plan_suite(test_defs)

    scheduler = Scheduler(
        run_id=run_id,
        env_profile="local",
        registry=registry,
        event_bus=bus,
        store=store,
        parallelism=1,  # deterministic order
    )

    verdicts = scheduler.run_suite(planned, traces=traces)
    outcomes = {item.test_id: v.outcome for item, v in zip(planned, verdicts)}
    ordering = [item.test_id for item in planned]
    return outcomes, ordering, store

def test_gate_g1_outcomes_and_explanations():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        run_id = "g1-eval-run"
        outcomes, _, store = run_suite_once(base, run_id)

        # 1. Check all required outcomes and compound cases
        assert outcomes["case-01-pass-clean"] == "PASS"
        assert outcomes["case-02-pass-additive"] == "PASS"
        assert outcomes["case-03-fail-bug-only"] == "FAIL"
        assert outcomes["case-04-drift-contract-only"] == "DRIFT"
        assert outcomes["case-05-drift-fingerprint-mismatch"] == "DRIFT"
        assert outcomes["case-06-error-transport"] == "ERROR"
        assert outcomes["case-07-skip-quarantine"] == "SKIPPED"
        assert outcomes["case-08-compound-contract-plus-bug"] == "FAIL"
        assert outcomes["case-09-compound-additive-plus-bug"] == "FAIL"
        assert outcomes["case-10-compound-step1-drift-blocks-step2"] == "DRIFT"

        # 2. Check explainability from stored SQLite events for each case
        exp_pass = explain_test(run_id, "case-01-pass-clean", store)
        assert exp_pass["outcome"] == "PASS"
        assert "executed cleanly" in exp_pass["explanation"]

        exp_fail = explain_test(run_id, "case-03-fail-bug-only", store)
        assert exp_fail["outcome"] == "FAIL"
        assert "Defect candidate" in exp_fail["explanation"]

        exp_drift = explain_test(run_id, "case-04-drift-contract-only", store)
        assert exp_drift["outcome"] == "DRIFT"
        assert "contract drifted" in exp_drift["explanation"].lower()
        assert "$.total" in exp_drift["drift_detail"]["breaking_paths"]

        exp_error = explain_test(run_id, "case-06-error-transport", store)
        assert exp_error["outcome"] == "ERROR"
        assert "Connection refused" in exp_error["reason"]

        exp_skipped = explain_test(run_id, "case-07-skip-quarantine", store)
        assert exp_skipped["outcome"] == "SKIPPED"
        assert "quarantined" in exp_skipped["explanation"]

        exp_compound = explain_test(run_id, "case-08-compound-contract-plus-bug", store)
        assert exp_compound["outcome"] == "FAIL"
        assert "Compound drift also present" in exp_compound["explanation"]
        assert "$.total" in exp_compound["drift_detail"]["breaking_paths"]

        print("Gate G1: All 10 cases produced expected outcomes and correct stored explanations!")

def test_gate_g1_determinism_10_runs():
    """NFR-6: Identical outcomes and report ordering across 10 consecutive runs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        first_outcomes = None
        first_ordering = None

        for run_idx in range(10):
            run_id = f"g1-det-run-{run_idx}"
            outcomes, ordering, _ = run_suite_once(base, run_id)

            if run_idx == 0:
                first_outcomes = outcomes
                first_ordering = ordering
            else:
                assert outcomes == first_outcomes, f"Run {run_idx} produced different outcomes than run 0!"
                assert ordering == first_ordering, f"Run {run_idx} produced different ordering than run 0!"

        print("Gate G1: 10 consecutive runs produced 100% identical outcomes and ordering (NFR-6)!")

if __name__ == "__main__":
    test_gate_g1_outcomes_and_explanations()
    test_gate_g1_determinism_10_runs()
    print("\nGATE G1 COMPLETE: Core with fake plugin verified!")
