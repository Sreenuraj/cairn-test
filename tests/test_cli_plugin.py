"""
Test for T7.1 / Acceptance 7: Second plugin proof.
Verifies that a CLI-command step type using only the contracts works cleanly
with zero changes to the core engine.
"""

from pathlib import Path
import tempfile

from cairn_test.core.events import EventBus, EventStore
from cairn_test.core.planner import Planner
from cairn_test.core.plugins import PluginRegistry
from cairn_test.core.scheduler import Scheduler
from cairn_test.plugins.cli import register_cli_plugin

def test_second_plugin_cli_steps():
    registry = PluginRegistry()
    register_cli_plugin(registry)

    # Define a test with CLI steps
    test_def = {
        "schema": "cairn-test.test/v1",
        "id": "echo_test",
        "steps": [
            {
                "id": "run_echo",
                "kind": "cli",
                "op": "echo",
                "args": {"command": "echo Hello, cairn-test!"},
            }
        ],
        "expect": [
            {"exit_code": 0},
            {"stdout_contains": "Hello, cairn-test!"},
        ],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        store = EventStore(base_dir=Path(tmpdir))
        bus = EventBus("run-cli-test", store=store)

        planner = Planner(event_bus=bus)
        planned = planner.plan_suite([test_def])
        assert len(planned) == 1
        assert planned[0].action == "EXECUTE"

        scheduler = Scheduler(
            run_id="run-cli-test",
            env_profile="local",
            registry=registry,
            event_bus=bus,
            store=store,
            parallelism=1,
        )

        verdicts = scheduler.run_suite(planned, traces={})
        assert len(verdicts) == 1
        v = verdicts[0]
        assert v.outcome == "PASS", f"Expected PASS, got {v.outcome}: {v.reason}"

    print("Second plugin proof (T7.1 / Acceptance 7) verified: CLI step executed successfully with zero core changes!")

if __name__ == "__main__":
    test_second_plugin_cli_steps()

