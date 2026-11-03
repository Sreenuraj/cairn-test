"""
Suite health analyzer and status view (T5.5, FR-O4).

Computes:
1. Flaky tests: tests exhibiting fluctuating outcomes across runs.
2. Drift rate: percentage of tests experiencing contract drift.
3. Quarantined tests: tests currently tagged or marked as quarantined with reasons.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import sqlite3

from cairn_test.core.events import EventStore
from cairn_test.core.planner import discover_tests

@dataclass
class SuiteHealth:
    total_tests: int
    total_runs: int
    drift_rate_percent: float
    flaky_tests: list[str]
    quarantined_tests: list[dict[str, Any]]
    latest_outcomes: dict[str, str]

class HealthAnalyzer:
    """Analyzes test suite health from stored events and test definitions."""

    def __init__(self, repo_root: Path | None = None, store: EventStore | None = None):
        self.repo_root = repo_root or Path(".")
        self.store = store or EventStore(base_dir=self.repo_root / ".cairn-test")

    def analyze(self) -> SuiteHealth:
        tests_dir = self.repo_root / "tests"
        discovered = discover_tests(tests_dir) if tests_dir.is_dir() else []
        total_tests = len(discovered)

        # Quarantined tests
        quarantined: list[dict[str, Any]] = []
        for t in discovered:
            is_q = False
            q_reason = None
            if t.get("quarantine"):
                is_q = True
                q_reason = t["quarantine"] if isinstance(t["quarantine"], dict) else "quarantined"
            elif "quarantine" in t.get("tags", []):
                is_q = True
                q_reason = "quarantine tag"
            if is_q:
                quarantined.append({"test_id": t["id"], "reason": str(q_reason)})

        # Query events from SQLite
        test_outcomes_history: dict[str, list[str]] = {}
        total_runs = 0

        db_path = self.repo_root / ".cairn-test" / "events.db"
        if db_path.is_file():
            try:
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                # Count distinct runs
                cur.execute("SELECT COUNT(DISTINCT run_id) FROM events")
                row = cur.fetchone()
                total_runs = row[0] if row else 0

                # Query test.finished events
                cur.execute(
                    "SELECT type, payload, timestamp FROM events WHERE type = 'test.finished' ORDER BY timestamp ASC"
                )
                import json
                for _, payload_str, _ in cur.fetchall():
                    try:
                        p = json.loads(payload_str)
                        tid = p.get("test_id")
                        outcome = p.get("outcome")
                        if tid and outcome:
                            test_outcomes_history.setdefault(tid, []).append(outcome)
                    except Exception:
                        pass
                conn.close()
            except Exception:
                pass

        # Calculate flakiness: tests having at least 2 distinct non-skipped outcomes
        flaky: list[str] = []
        latest_outcomes: dict[str, str] = {}
        for tid, history in test_outcomes_history.items():
            if history:
                latest_outcomes[tid] = history[-1]
                distinct = set(h for h in history if h != "SKIPPED")
                if len(distinct) > 1:
                    flaky.append(tid)

        # Drift rate
        drifted_count = sum(1 for o in latest_outcomes.values() if o == "DRIFT")
        drift_rate = (drifted_count / total_tests * 100.0) if total_tests > 0 else 0.0

        return SuiteHealth(
            total_tests=total_tests,
            total_runs=total_runs,
            drift_rate_percent=round(drift_rate, 2),
            flaky_tests=sorted(flaky),
            quarantined_tests=quarantined,
            latest_outcomes=latest_outcomes,
        )
