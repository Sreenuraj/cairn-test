"""
Performance baseline measurement (T2.9, NFR-2, NFR-3).

Measures:
1. Replay overhead per step (excluding network HTTP call) -> Target: < 5 ms.
2. Planning time for 1,000 test definitions -> Target: < 2 s.
"""

from pathlib import Path
import sys
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cairn_test.contracts import Observation, ResolvedStep, RunContext, StepResult
from cairn_test.core.planner import Planner
from cairn_test.core.plugins import PluginRegistry, PluginWrapper

class ZeroDurationExecutor:
    kind = "bench"
    def execute(self, step: ResolvedStep, ctx: RunContext) -> StepResult:
        return StepResult(step.id, status_code=200, data={"ok": True}, duration_ms=0.0)

class FastObserver:
    def observe(self, result: StepResult) -> Observation:
        return Observation(status=200, headers=["content-type"], body_shape={"ok": "boolean"})

    def compare(self, recorded: Observation, observed: Observation) -> Any:
        from cairn_test.contracts import ObservationDiff
        return ObservationDiff()

def test_nfr2_step_overhead():
    import tempfile
    from cairn_test.core.events import EventBus, EventStore

    with tempfile.TemporaryDirectory() as tmp_dir:
        registry = PluginRegistry()
        registry.register_step_executor("bench", ZeroDurationExecutor())
        registry.register_observer("bench", FastObserver())

        store = EventStore(base_dir=tmp_dir)
        bus = EventBus("bench-run", store=store)
        wrapper = PluginWrapper(registry, bus)

        step = ResolvedStep("s1", "bench", "op", "GET", "/test")
        ctx = RunContext("bench-run", "w-0", "local")
        rec_obs = Observation(200, ["content-type"], {"ok": "boolean"})

        # Warmup
        for _ in range(100):
            res = wrapper.execute_step(step, ctx)
            wrapper.observe_and_diff("bench", "s1", rec_obs, res)

        # Measure 1,000 steps
        iterations = 1000
        start_t = time.perf_counter()
        for _ in range(iterations):
            res = wrapper.execute_step(step, ctx)
            wrapper.observe_and_diff("bench", "s1", rec_obs, res)
        total_elapsed = time.perf_counter() - start_t

        overhead_ms_per_step = (total_elapsed / iterations) * 1000.0
        print(f"NFR-2 Measurement: {overhead_ms_per_step:.3f} ms per step (Target: < 5.0 ms)")
        assert overhead_ms_per_step < 5.0, f"NFR-2 Failed: overhead was {overhead_ms_per_step:.2f} ms"

def test_nfr3_planning_1000_tests():
    planner = Planner(tag_filter=["smoke"])

    # Generate 1,000 test definitions
    tests = [
        {
            "schema": "cairn-test.test/v1",
            "id": f"test-{i}",
            "tags": ["smoke" if i % 2 == 0 else "regression"],
            "steps": [{"id": "s1", "op": "login"}],
        }
        for i in range(1000)
    ]

    start_t = time.perf_counter()
    planned = planner.plan_suite(tests)
    elapsed_sec = time.perf_counter() - start_t

    print(f"NFR-3 Measurement: Planning 1,000 tests took {elapsed_sec:.4f} s (Target: < 2.0 s)")
    assert len(planned) == 1000
    assert elapsed_sec < 2.0, f"NFR-3 Failed: planning took {elapsed_sec:.2f} s"

if __name__ == "__main__":
    from typing import Any
    test_nfr2_step_overhead()
    test_nfr3_planning_1000_tests()
    print("All T2.9 performance baseline targets confirmed!")
