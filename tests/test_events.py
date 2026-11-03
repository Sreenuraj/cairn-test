"""
Tests for EventBus, JSONL writer, SQLite store, and artifact store (T1.3, FR-C7, FR-C8, FR-O6, FR-P4).
"""

import json
import sqlite3
import tempfile
from pathlib import Path
from cairn_test.core.events import EventBus, EventStore, FRAMEWORK_VERSION
from cairn_test.core.schemas import load_event, load_result

def test_event_bus_and_stores():
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = EventStore(base_dir=tmp_dir)
        run_id = "test-run-101"
        bus = EventBus(run_id=run_id, store=store)

        received_events = []
        bus.subscribe(lambda e: received_events.append(e))

        # 1. Emit lifecycle events
        e1 = bus.emit("run.started", {"env": "local"})
        e2 = bus.emit("test.planned", {"test_id": "test-1", "action": "EXECUTE"})
        e3 = bus.emit("step.executed", {"step_id": "login", "status": 200})
        e4 = bus.emit("run.finished", {"outcome": "PASS", "total": 1, "passed": 1})

        assert len(received_events) == 4
        assert e1["sequence"] == 0
        assert e2["sequence"] == 1
        assert e3["sequence"] == 2
        assert e4["sequence"] == 3

        # Validate event schema
        for e in received_events:
            load_event(e)

        # 2. Verify JSONL writer
        jsonl_path = Path(tmp_dir) / "runs" / run_id / "events.jsonl"
        assert jsonl_path.is_file()
        with open(jsonl_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 4
        assert lines[0]["type"] == "run.started"
        assert lines[3]["type"] == "run.finished"

        # 3. Verify SQLite store & plain SQL queryability (FR-O6)
        db_path = Path(tmp_dir) / "events.db"
        assert db_path.is_file()

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM events WHERE run_id = ? ORDER BY sequence ASC", (run_id,)).fetchall()
            assert len(rows) == 4
            assert rows[0]["type"] == "run.started"
            assert rows[3]["type"] == "run.finished"

            run_row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            assert run_row["outcome"] == "PASS"
            assert run_row["passed"] == 1

        # 4. Record result and verify framework & plugin versions (FR-P4)
        result_doc = {
            "schema": "cairn-test.result/v1",
            "run_id": run_id,
            "test": "test-1",
            "outcome": "PASS",
            "duration_ms": 35.2,
            "versions": {
                "framework": FRAMEWORK_VERSION,
                "plugins": {"fake": "0.1.0"}
            },
            "recorded_at": "2026-11-03T10:00:05Z"
        }
        load_result(result_doc)
        store.record_result(result_doc)

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            res_row = conn.execute("SELECT * FROM results WHERE run_id = ? AND test_id = ?", (run_id, "test-1")).fetchone()
            assert res_row["outcome"] == "PASS"
            assert FRAMEWORK_VERSION in res_row["versions"]
            assert "fake" in res_row["versions"]

        # 5. Verify artifact store
        art_path = store.store_artifact(run_id, "response.json", '{"status": "ok"}', media_type="application/json")
        assert art_path.is_file()
        assert art_path.read_text(encoding="utf-8") == '{"status": "ok"}'

        print("EventBus, JSONL, SQLite, and Artifact store tests PASSED!")

if __name__ == "__main__":
    test_event_bus_and_stores()
