"""
Tests for API plugin against reference target API (T2.8).
Runs all 12 core behaviors against the unseeded target API and verifies 100% PASS.
"""

from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bench.service.api import StoreApiHandler, start_reference_server
from cairn_test.core.events import EventBus, EventStore
from cairn_test.core.planner import Planner, discover_tests
from cairn_test.core.plugins import PluginRegistry
from cairn_test.core.scheduler import Scheduler
from cairn_test.core.schemas import load_trace
from cairn_test.plugins.api.plugin import register_api_plugin
from cairn_test.plugins.api.spec import OpenAPISpec

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "bench" / "tests"
TRACES_DIR = REPO_ROOT / "bench" / "traces"
SPEC_FILE = REPO_ROOT / "bench" / "service" / "openapi.yaml"

def test_api_plugin_against_reference_api():
    server, base_url = start_reference_server(port=0)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        StoreApiHandler.store.reset()
        spec = OpenAPISpec.load(SPEC_FILE)

        # Discover tests
        discovered_tests = discover_tests(TESTS_DIR)
        assert len(discovered_tests) == 12, f"Expected 12 tests, got {len(discovered_tests)}"

        # Load traces
        traces_map = {}
        for p in TRACES_DIR.glob("*.trace.yaml"):
            tr = load_trace(p)
            traces_map[tr["test"]] = tr
        assert len(traces_map) == 12, f"Expected 12 traces, got {len(traces_map)}"

        registry = PluginRegistry()
        register_api_plugin(registry, spec=spec, base_url=base_url)

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = EventStore(base_dir=tmp_dir)
            bus = EventBus(run_id="run-ref-test", store=store)
            planner = Planner(event_bus=bus)
            planned = planner.plan_suite(discovered_tests)

            scheduler = Scheduler(
                run_id="run-ref-test",
                env_profile="local",
                registry=registry,
                event_bus=bus,
                store=store,
                parallelism=1,
            )

            verdicts = scheduler.run_suite(planned, traces=traces_map)
            assert len(verdicts) == 12

            for item, v in zip(planned, verdicts):
                assert v.outcome == "PASS", f"Test '{item.test_id}' failed: outcome={v.outcome}, reason={v.reason}"

        print(f"All 12 core behaviors PASSED against the reference target API!")
    finally:
        server.shutdown()

if __name__ == "__main__":
    test_api_plugin_against_reference_api()
