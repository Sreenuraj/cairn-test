"""
Event bus, JSONL writer, SQLite store, and artifact store (T1.3, FR-C7, FR-C8, FR-O6, FR-P4).
"""

from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable

FRAMEWORK_VERSION = "0.1.0"

class EventStore:
    """Manages persistence of events and test run results in JSONL and SQLite."""

    def __init__(self, base_dir: Path | str = ".cairn-test"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_dir / "events.db"
        self._init_sqlite()

    def _init_sqlite(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    outcome TEXT,
                    total_tests INTEGER DEFAULT 0,
                    passed INTEGER DEFAULT 0,
                    failed INTEGER DEFAULT 0,
                    drifted INTEGER DEFAULT 0,
                    errored INTEGER DEFAULT 0,
                    skipped INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (run_id, sequence)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_run_type ON events(run_id, type)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS results (
                    run_id TEXT NOT NULL,
                    test_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    duration_ms REAL NOT NULL,
                    reason TEXT,
                    drift_detail TEXT,
                    versions TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, test_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_results_outcome ON results(outcome)")
            conn.commit()

    def get_run_dir(self, run_id: str) -> Path:
        d = self.base_dir / "runs" / run_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def record_event(self, event: dict[str, Any]) -> None:
        run_id = event["run_id"]
        run_dir = self.get_run_dir(run_id)

        # 1. JSONL writer
        jsonl_path = run_dir / "events.jsonl"
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

        # 2. SQLite store
        payload_str = json.dumps(event.get("payload", {}))
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO events (run_id, sequence, timestamp, type, payload) VALUES (?, ?, ?, ?, ?)",
                (run_id, event["sequence"], event["timestamp"], event["type"], payload_str),
            )
            if event["type"] == "run.started":
                conn.execute(
                    "INSERT OR IGNORE INTO runs (run_id, started_at) VALUES (?, ?)",
                    (run_id, event["timestamp"]),
                )
            elif event["type"] == "run.finished":
                p = event.get("payload", {})
                conn.execute(
                    """UPDATE runs SET finished_at = ?, outcome = ?, total_tests = ?,
                       passed = ?, failed = ?, drifted = ?, errored = ?, skipped = ?
                       WHERE run_id = ?""",
                    (
                        event["timestamp"],
                        p.get("outcome", "UNKNOWN"),
                        p.get("total", 0),
                        p.get("passed", 0),
                        p.get("failed", 0),
                        p.get("drifted", 0),
                        p.get("errored", 0),
                        p.get("skipped", 0),
                        run_id,
                    ),
                )
            conn.commit()

    def record_result(self, result: dict[str, Any]) -> None:
        run_id = result["run_id"]
        test_id = result["test"]
        versions_str = json.dumps(result.get("versions", {"framework": FRAMEWORK_VERSION, "plugins": {}}))
        drift_str = json.dumps(result.get("drift_detail")) if result.get("drift_detail") else None

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO results
                   (run_id, test_id, outcome, duration_ms, reason, drift_detail, versions, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    test_id,
                    result["outcome"],
                    float(result["duration_ms"]),
                    result.get("reason"),
                    drift_str,
                    versions_str,
                    result["recorded_at"],
                ),
            )
            conn.commit()

    def store_artifact(self, run_id: str, name: str, content: bytes | str, media_type: str = "text/plain") -> Path:
        artifacts_dir = self.get_run_dir(run_id) / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        file_path = artifacts_dir / name
        if isinstance(content, str):
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
        else:
            with open(file_path, "wb") as f:
                f.write(content)
        return file_path

    def query_events(self, run_id: str, event_type: str | None = None) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if event_type:
                cursor = conn.execute(
                    "SELECT * FROM events WHERE run_id = ? AND type = ? ORDER BY sequence ASC",
                    (run_id, event_type),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM events WHERE run_id = ? ORDER BY sequence ASC",
                    (run_id,),
                )
            rows = cursor.fetchall()
            return [
                {
                    "run_id": r["run_id"],
                    "sequence": r["sequence"],
                    "timestamp": r["timestamp"],
                    "type": r["type"],
                    "payload": json.loads(r["payload"]),
                }
                for r in rows
            ]

class EventBus:
    """Core event bus emitting structured events and dispatching to store."""

    def __init__(self, run_id: str, store: EventStore | None = None):
        self.run_id = run_id
        self.store = store or EventStore()
        self.sequence = 0
        self.subscribers: list[Callable[[dict[str, Any]], None]] = []

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self.subscribers.append(callback)

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        now_utc = datetime.now(timezone.utc).isoformat()
        event = {
            "schema": "cairn-test.event/v1",
            "run_id": self.run_id,
            "sequence": self.sequence,
            "timestamp": now_utc,
            "type": event_type,
            "payload": payload or {},
        }
        self.sequence += 1

        # Persist
        self.store.record_event(event)

        # Notify subscribers
        for sub in self.subscribers:
            sub(event)

        return event
