"""
Tests for PluginRegistry and PluginWrapper (T1.4, FR-P2, FR-P3).
"""

import tempfile
from cairn_test.contracts import (
    ResolvedStep,
    StepResult,
    Observation,
    ObservationDiff,
    DiffChange,
    DiffKind,
    RunContext,
)
from cairn_test.core.events import EventBus, EventStore
from cairn_test.core.plugins import PluginRegistry, PluginWrapper

class MockExecutor:
    kind = "mock"
    def execute(self, step: ResolvedStep, ctx: RunContext) -> StepResult:
        if step.operation == "crash":
            raise RuntimeError("Hardware failure simulation")
        return StepResult(step_id=step.id, status_code=200, data={"ok": True})

class MockObserver:
    def observe(self, result: StepResult) -> Observation:
        return Observation(status=result.status_code or 0, headers=["content-type"], body_shape={"ok": "boolean"})

    def compare(self, recorded: Observation, observed: Observation) -> ObservationDiff:
        if recorded.status != observed.status:
            return ObservationDiff(changes=[
                DiffChange(path="$.status", kind=DiffKind.BREAKING, recorded=recorded.status, observed=observed.status)
            ])
        return ObservationDiff()

def test_plugin_registry_and_wrapper():
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = EventStore(base_dir=tmp_dir)
        bus = EventBus(run_id="run-plugin-test", store=store)
        registry = PluginRegistry()

        # Register plugin components
        registry.register_step_executor("mock", MockExecutor(), version="1.0.0")
        registry.register_observer("mock", MockObserver())

        assert registry.get_step_executor("mock").kind == "mock"
        assert registry.versions["mock"] == "1.0.0"

        wrapper = PluginWrapper(registry=registry, event_bus=bus, store=store)
        ctx = RunContext(run_id="run-plugin-test", worker_id="w-1", env_profile="local")

        # 1. Normal execution
        step = ResolvedStep(id="step-1", kind="mock", operation="fetch", method="GET", path="/test")
        result = wrapper.execute_step(step, ctx)
        assert result.status_code == 200
        assert result.transport_error is None
        assert result.duration_ms > 0

        # Verify event emitted
        events = store.query_events("run-plugin-test", event_type="step.executed")
        assert len(events) == 1
        assert events[0]["payload"]["step_id"] == "step-1"
        assert events[0]["payload"]["status_code"] == 200

        # 2. Execution with exception caught into transport_error
        crash_step = ResolvedStep(id="step-crash", kind="mock", operation="crash", method="GET", path="/crash")
        crash_result = wrapper.execute_step(crash_step, ctx)
        assert crash_result.status_code is None
        assert "Hardware failure simulation" in (crash_result.transport_error or "")

        events_after = store.query_events("run-plugin-test", event_type="step.executed")
        assert len(events_after) == 2
        assert events_after[1]["payload"]["step_id"] == "step-crash"
        assert "Hardware failure" in events_after[1]["payload"]["transport_error"]

        # 3. Observe and diff wrapper
        rec_obs = Observation(status=200, headers=["content-type"], body_shape={"ok": "boolean"})
        observed, diff = wrapper.observe_and_diff("mock", "step-1", rec_obs, result)
        assert not diff.has_breaking

        diff_events = store.query_events("run-plugin-test", event_type="observation.diffed")
        assert len(diff_events) == 1
        assert diff_events[0]["payload"]["step_id"] == "step-1"
        assert diff_events[0]["payload"]["has_breaking"] is False

        print("PluginRegistry and PluginWrapper tests PASSED!")

if __name__ == "__main__":
    test_plugin_registry_and_wrapper()
