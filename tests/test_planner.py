"""
Tests for planner (T1.7, FR-C3, FR-C11).
"""

import tempfile
from cairn_test.core.events import EventBus, EventStore
from cairn_test.core.planner import Planner, PlanItem

def test_planner_selection_and_quarantine():
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = EventStore(base_dir=tmp_dir)
        bus = EventBus(run_id="run-plan-1", store=store)

        tests = [
            {"schema": "cairn-test.test/v1", "id": "test-smoke-1", "tags": ["smoke", "orders"], "steps": [{"id": "s1", "op": "login"}]},
            {"schema": "cairn-test.test/v1", "id": "test-auth-2", "tags": ["auth"], "steps": [{"id": "s1", "op": "login"}]},
            {"schema": "cairn-test.test/v1", "id": "test-flaky-3", "tags": ["orders"], "quarantine": {"reason": "db flakiness"}, "steps": [{"id": "s1", "op": "login"}]},
        ]

        # 1. Plan with tag filter "smoke"
        planner = Planner(event_bus=bus, tag_filter=["smoke"])
        planned = planner.plan_suite(tests)

        assert planned[0].test_id == "test-smoke-1"
        assert planned[0].action == "EXECUTE"

        assert planned[1].test_id == "test-auth-2"
        assert planned[1].action == "SKIPPED"
        assert planned[1].reason == "filter:tag"

        # Quarantined test is skipped even if matching tags
        assert planned[2].test_id == "test-flaky-3"
        assert planned[2].action == "SKIPPED"
        assert "quarantined:db flakiness" in planned[2].reason

        # Verify test.planned events recorded
        events = store.query_events("run-plan-1", event_type="test.planned")
        assert len(events) == 3
        assert events[0]["payload"]["action"] == "EXECUTE"
        assert events[1]["payload"]["action"] == "SKIPPED"
        assert events[2]["payload"]["action"] == "SKIPPED"

        # 2. Plan with ID filter
        bus2 = EventBus(run_id="run-plan-2", store=store)
        id_planner = Planner(event_bus=bus2, id_filter=["test-auth-2"])
        planned_id = id_planner.plan_suite(tests)
        assert planned_id[0].action == "SKIPPED"
        assert planned_id[0].reason == "filter:id"
        assert planned_id[1].action == "EXECUTE"

        print("Planner tests PASSED!")

if __name__ == "__main__":
    test_planner_selection_and_quarantine()
