"""
Time-logging protocol for cairn-test benchmark (T6.3, FR-B3).

Records:
- tool: "cairn-test" | "newman" | "rest-assured"
- task_id: behavior or seeded change ID
- triage_time_s: wall-clock seconds from test failure to root-cause identification
- fix_time_s: wall-clock seconds from root-cause identification to verified fix
- review_time_s: wall-clock seconds spent reviewing diffs/proposals
- authored_lines: number of code or YAML lines authored/modified
"""

from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

@dataclass
class TimeLogEntry:
    timestamp: str
    tool: str
    task_id: str
    triage_time_s: float
    fix_time_s: float
    review_time_s: float
    authored_lines: int
    notes: str = ""

class TimeLogger:
    def __init__(self, log_file: Path | str | None = None):
        if log_file:
            self.log_file = Path(log_file)
        else:
            self.log_file = Path(__file__).parent / "results" / "timelog.jsonl"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        tool: str,
        task_id: str,
        triage_time_s: float,
        fix_time_s: float,
        review_time_s: float,
        authored_lines: int,
        notes: str = "",
    ) -> TimeLogEntry:
        entry = TimeLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            tool=tool,
            task_id=task_id,
            triage_time_s=round(triage_time_s, 2),
            fix_time_s=round(fix_time_s, 2),
            review_time_s=round(review_time_s, 2),
            authored_lines=authored_lines,
            notes=notes,
        )
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry)) + "\n")
        return entry

    def load_entries(self) -> list[TimeLogEntry]:
        if not self.log_file.is_file():
            return []
        entries = []
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(TimeLogEntry(**json.loads(line)))
                    except Exception:
                        pass
        return entries

