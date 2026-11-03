"""
Tests for scheduler and workers (T1.8, FR-C4, FR-C18).
"""

import tempfile
import time
from typing import Any
from cairn_test.contracts import ResolvedStep, StepResult, RunContext
from cairn_test.core.events import EventBus, EventStore
from cairn_test.core.planner import PlanItem
from cairn_test.core.plugins import PluginRegistry
from cairn_test.core.scheduler import Scheduler, interpolate

class DummyStepExecutor:
    kind = "http"
    def __init__(self):
        self.invocations: list[dict[str, Any]] = []

    def execute(self, step: ResolvedStep, ctx: RunContext) -> StepResult:
        self.invocations.append({
            "worker_id": ctx.worker_id,
            "variables": dict(ctx.variables),
            "step_id": step.id,
            "body": step.body,
        })
        time.sleep(0.01)  # small work simulation
        return StepResult(step_id=step.id, status_code=200, data={"id": f"id-{step.id}"})

class DummyObserver:
    def observe(self, result: StepResult) -> Any:
        from cairn_test.contracts import Observation
        return Observation(status=result.status_code or 200)

    def compare(self, recorded: Any, observed: Any) -> Any:
        from cairn_test.contracts import ObservationDiff
        return ObservationDiff()

def test_variable_interpolation():
    vars = {"run.uid": "abc1234", "worker.id": "w-0", "order_id": 42}
    res = interpolate("{run.uid}-order", vars)
    assert res == "abc1234-order"

    nested = {"ref": "{worker.id}", "items": [{"id": "{order_id}"}]}
    res_nested = interpolate(nested, vars)
    assert res_nested["ref"] == "w-0"
    assert res_nested["items"][0]["id"] == 42

def test_scheduler_parallel_and_serial():
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = EventStore(base_dir=tmp_dir)
        bus = EventBus(run_id="run-sched-1", store=store)

        registry = PluginRegistry()
        executor = DummyStepExecutor()
        registry.register_step_executor("http", executor)
        registry.register_observer("http", DummyObserver())

        # Test items: 2 hermetic (can run parallel), 1 non-hermetic (runs serially)
        test_h1 = {
            "schema": "cairn-test.test/v1",
            "id": "test-hermetic-1",
            "data": {"order_ref": "{run.uid}-h1"},
            "steps": [{"id": "s1", "op": "create", "args": {"body": "{order_ref}"}}],
            "expect": [{"after": "s1", "status": 200}],
        }
        test_h2 = {
            "schema": "cairn-test.test/v1",
            "id": "test-hermetic-2",
            "data": {"order_ref": "{run.uid}-h2"},
            "steps": [{"id": "s1", "op": "create", "args": {"body": "{order_ref}"}}],
            "expect": [{"after": "s1", "status": 200}],
        }
        test_serial = {
            "schema": "cairn-test.test/v1",
            "id": "test-serial-3",
            "hermetic": False,
            "data": {"order_ref": "{run.uid}-serial"},
            "steps": [{"id": "s1", "op": "create", "args": {"body": "{order_ref}"}}],
            "expect": [{"after": "s1", "status": 200}],
        }

        items = [
            PlanItem(test_id="test-hermetic-1", test_def=test_h1, action="EXECUTE", hermetic=True),
            PlanItem(test_id="test-hermetic-2", test_def=test_h2, action="EXECUTE", hermetic=True),
            PlanItem(test_id="test-serial-3", test_def=test_serial, action="EXECUTE", hermetic=False),
        ]

        scheduler = Scheduler(
            run_id="run-sched-1",
            env_profile="local",
            registry=registry,
            event_bus=bus,
            store=store,
            parallelism=2,
        )

        verdicts = scheduler.run_suite(items)
        assert len(verdicts) == 3
        for v in verdicts:
            assert v.outcome == "PASS"

        # Check invocations and worker isolation
        assert len(executor.invocations) == 3
        bodies = [inv["body"] for inv in executor.invocations]
        assert "1-h1" in bodies
        assert "1-h2" in bodies
        assert "1-serial" in bodies

        # Verify test.finished events recorded in SQLite
        events = store.query_events("run-sched-1", event_type="test.finished")
        assert len(events) == 3

        print("Scheduler and worker tests PASSED!")

if __name__ == "__main__":
    test_variable_interpolation()
    test_scheduler_parallel_and_serial()
