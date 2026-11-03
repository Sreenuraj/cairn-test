"""
Planner for cairn-test core (T1.7, FR-C3, FR-C11).

Plans each discovered test as EXECUTE or SKIPPED (tag filter, ID filter, quarantine)
and emits test.planned events with reasons.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from cairn_test.core.events import EventBus
from cairn_test.core.schemas import load_test

@dataclass
class PlanItem:
    test_id: str
    test_def: dict[str, Any]
    action: str  # "EXECUTE" | "SKIPPED"
    reason: str | None = None
    hermetic: bool = True

class Planner:
    def __init__(
        self,
        event_bus: EventBus | None = None,
        tag_filter: list[str] | None = None,
        id_filter: list[str] | None = None,
        include_quarantined: bool = False,
    ):
        self.event_bus = event_bus
        self.tag_filter = set(tag_filter) if tag_filter else None
        self.id_filter = set(id_filter) if id_filter else None
        self.include_quarantined = include_quarantined

    def plan_test(self, test_def: dict[str, Any]) -> PlanItem:
        test_id = test_def["id"]
        hermetic = test_def.get("hermetic", True)

        # 1. Quarantine check
        tags = set(test_def.get("tags", []))
        quarantine = test_def.get("quarantine") or ("quarantine" in tags)
        if quarantine and not self.include_quarantined:
            reason = "quarantined"
            if isinstance(quarantine, dict) and "reason" in quarantine:
                reason = f"quarantined:{quarantine['reason']}"
            item = PlanItem(test_id=test_id, test_def=test_def, action="SKIPPED", reason=reason, hermetic=hermetic)
            self._emit_planned(item)
            return item

        # 2. ID filter
        if self.id_filter is not None and test_id not in self.id_filter:
            item = PlanItem(test_id=test_id, test_def=test_def, action="SKIPPED", reason="filter:id", hermetic=hermetic)
            self._emit_planned(item)
            return item

        # 3. Tag filter
        if self.tag_filter is not None:
            tags = set(test_def.get("tags", []))
            if not (tags & self.tag_filter):
                item = PlanItem(test_id=test_id, test_def=test_def, action="SKIPPED", reason="filter:tag", hermetic=hermetic)
                self._emit_planned(item)
                return item

        # 4. Selected to execute
        item = PlanItem(test_id=test_id, test_def=test_def, action="EXECUTE", reason=None, hermetic=hermetic)
        self._emit_planned(item)
        return item

    def plan_suite(self, test_defs: list[dict[str, Any]]) -> list[PlanItem]:
        expanded_tests: list[dict[str, Any]] = []
        for t in test_defs:
            # Handle parametrization (T5.10, FR-C17)
            if "parametrize" in t and isinstance(t["parametrize"], dict):
                p_spec = t["parametrize"]
                param_names = p_spec.get("params", [])
                cases = p_spec.get("cases", [])
                for i, case in enumerate(cases):
                    t_copy = dict(t)
                    t_copy["id"] = f"{t['id']}[{i}]"
                    t_copy_data = dict(t.get("data", {}))
                    for name, val in zip(param_names, case):
                        t_copy_data[name] = val
                    t_copy["data"] = t_copy_data
                    expanded_tests.append(t_copy)
            else:
                expanded_tests.append(t)

        # Handle fixtures (setup / teardown steps)
        for t in expanded_tests:
            if "fixtures" in t and isinstance(t["fixtures"], dict):
                setup_steps = t["fixtures"].get("setup", [])
                teardown_steps = t["fixtures"].get("teardown", [])
                if setup_steps or teardown_steps:
                    steps = list(setup_steps) + list(t.get("steps", [])) + list(teardown_steps)
                    t["steps"] = steps

        return [self.plan_test(t) for t in expanded_tests]

    def _emit_planned(self, item: PlanItem) -> None:
        if self.event_bus:
            self.event_bus.emit("test.planned", {
                "test_id": item.test_id,
                "action": item.action,
                "reason": item.reason,
                "hermetic": item.hermetic,
            })

def discover_tests(tests_dir: Path | str) -> list[dict[str, Any]]:
    p = Path(tests_dir)
    if not p.is_dir():
        return []
    tests: list[dict[str, Any]] = []
    # Search for *.test.yaml and *.test.yml
    for pattern in ["*.test.yaml", "*.test.yml"]:
        for file in sorted(p.glob(pattern)):
            tests.append(load_test(file))
    return tests
