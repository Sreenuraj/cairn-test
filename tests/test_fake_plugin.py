"""
Tests for FakePlugin (T1.9, FR-C10).
Verifies that the fake plugin can drive the full lifecycle and script every outcome
and compound case.
"""

import tempfile
from cairn_test.core.events import EventBus, EventStore
from cairn_test.core.planner import PlanItem
from cairn_test.core.plugins import PluginRegistry
from cairn_test.core.scheduler import Scheduler
from cairn_test.plugins.fake import register_fake_plugin

def test_fake_plugin_drives_all_outcomes():
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = EventStore(base_dir=tmp_dir)
        bus = EventBus(run_id="run-fake-test", store=store)
        registry = PluginRegistry()
        register_fake_plugin(registry)

        scheduler = Scheduler(
            run_id="run-fake-test",
            env_profile="local",
            registry=registry,
            event_bus=bus,
            store=store,
            parallelism=1,
        )

        # 1. PASS test
        test_pass = {
            "schema": "cairn-test.test/v1",
            "id": "t-pass",
            "steps": [{"id": "s1", "kind": "fake", "op": "step1", "args": {"status": 200, "data": {"total": 50}}}],
            "expect": [{"after": "s1", "fake": {"reads": ["$.total"], "evaluate": True}}],
        }
        trace_pass = {
            "steps": [{
                "id": "s1",
                "observation": {"status": 200, "body_shape": {"total": "int"}},
                "pre_fingerprint": {"op_hash": "hash-step1"}
            }]
        }

        # 2. FAIL test (pure bug)
        test_fail = {
            "schema": "cairn-test.test/v1",
            "id": "t-fail",
            "steps": [{"id": "s1", "kind": "fake", "op": "step1", "args": {"status": 200, "data": {"total": 50}}}],
            "expect": [{"after": "s1", "fake": {"reads": ["$.total"], "evaluate": False}}],
        }

        # 3. DRIFT test (breaking field removed -> expectation unevaluable)
        test_drift = {
            "schema": "cairn-test.test/v1",
            "id": "t-drift",
            "steps": [{"id": "s1", "kind": "fake", "op": "step1", "args": {"status": 200, "data": {}}}],  # total removed
            "expect": [{"after": "s1", "fake": {"reads": ["$.total"], "evaluate": "missing"}}],
        }
        trace_drift = {
            "steps": [{
                "id": "s1",
                "observation": {"status": 200, "body_shape": {"total": "int"}},
                "pre_fingerprint": {"op_hash": "hash-step1"}
            }]
        }

        # 4. ERROR test (transport error connection refused)
        test_error = {
            "schema": "cairn-test.test/v1",
            "id": "t-error",
            "steps": [{"id": "s1", "kind": "fake", "op": "step1", "args": {"transport_error": "Connection refused"}}],
            "expect": [{"after": "s1", "fake": {"reads": ["$.status"], "evaluate": "missing"}}],
        }

        # 5. Compound case: Contract change (field removed) + bug (false expectation) -> FAIL with drift detail
        test_compound = {
            "schema": "cairn-test.test/v1",
            "id": "t-compound",
            "steps": [{"id": "s1", "kind": "fake", "op": "step1", "args": {"status": 200, "data": {"status": "ACTIVE"}}}],
            "expect": [
                {"after": "s1", "fake": {"reads": ["$.total"], "evaluate": "missing"}},
                {"after": "s1", "fake": {"reads": ["$.status"], "evaluate": False}},
            ],
        }
        trace_compound = {
            "steps": [{
                "id": "s1",
                "observation": {"status": 200, "body_shape": {"total": "int", "status": "str"}},
                "pre_fingerprint": {"op_hash": "hash-step1"}
            }]
        }

        items = [
            PlanItem(test_id="t-pass", test_def=test_pass, action="EXECUTE"),
            PlanItem(test_id="t-fail", test_def=test_fail, action="EXECUTE"),
            PlanItem(test_id="t-drift", test_def=test_drift, action="EXECUTE"),
            PlanItem(test_id="t-error", test_def=test_error, action="EXECUTE"),
            PlanItem(test_id="t-compound", test_def=test_compound, action="EXECUTE"),
            PlanItem(test_id="t-skipped", test_def={"schema": "cairn-test.test/v1", "id": "t-skipped", "steps": []}, action="SKIPPED", reason="quarantined"),
        ]

        traces = {
            "t-pass": trace_pass,
            "t-drift": trace_drift,
            "t-compound": trace_compound,
        }

        verdicts = scheduler.run_suite(items, traces=traces)
        results = {v.outcome: v for v in verdicts}

        v_pass = next(v for v in verdicts if v.outcome == "PASS")
        v_fail = next(v for v in verdicts if v.outcome == "FAIL" and not v.has_drift_detail)
        v_drift = next(v for v in verdicts if v.outcome == "DRIFT")
        v_error = next(v for v in verdicts if v.outcome == "ERROR")
        v_compound = next(v for v in verdicts if v.outcome == "FAIL" and v.has_drift_detail)
        v_skip = next(v for v in verdicts if v.outcome == "SKIPPED")

        assert v_pass is not None
        assert v_fail is not None
        assert v_drift is not None
        assert v_error is not None
        assert v_compound is not None
        assert v_compound.has_drift_detail is True
        assert v_skip is not None
        assert v_skip.reason == "quarantined"

        print("Fake plugin drove all outcomes and compound cases successfully!")

if __name__ == "__main__":
    test_fake_plugin_drives_all_outcomes()
