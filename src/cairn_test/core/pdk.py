"""
Plugin Developer Kit (PDK) Scaffolder for cairn-test (T8.3).

Generates standalone, domain-neutral plugin scaffolds implementing the 5 core contracts:
1. StepExecutor
2. Observer
3. Fingerprinter
4. AssertionType
5. EvidenceCollector
"""

from __future__ import annotations
from pathlib import Path
import re
from typing import Any

TEMPLATE_INIT = '''"""
{name_title} Plugin for cairn-test.
Domain-neutral extension implementing the 5 cairn-test plugin contracts.
"""

from __future__ import annotations
from cairn_test.core.plugins import PluginRegistry
from .executor import {name_pascal}StepExecutor
from .observer import {name_pascal}Observer
from .fingerprint import {name_pascal}Fingerprinter
from .assertions import {name_pascal}StatusAssertion
from .evidence import {name_pascal}EvidenceCollector

def register_{name_snake}_plugin(registry: PluginRegistry) -> None:
    """Register all 5 contracts with the PluginRegistry."""
    registry.register_step_executor("{name_snake}", {name_pascal}StepExecutor(), version="0.1.0")
    registry.register_observer("{name_snake}", {name_pascal}Observer())
    registry.register_fingerprinter("{name_snake}", {name_pascal}Fingerprinter())
    registry.register_evidence_collector("{name_snake}", {name_pascal}EvidenceCollector())
    registry.register_assertion("{name_snake}_status", {name_pascal}StatusAssertion())
'''

TEMPLATE_EXECUTOR = '''"""StepExecutor contract implementation."""
from __future__ import annotations
import time
from typing import Any
from cairn_test.contracts import ResolvedStep, RunContext, StepResult

class {name_pascal}StepExecutor:
    """Executes {name_title} steps against the target system."""
    kind: str = "{name_snake}"

    def execute(self, step: ResolvedStep, ctx: RunContext) -> StepResult:
        start_time = time.perf_counter()
        action = step.operation or step.path or "default_action"
        params = step.params or {{}}

        # Simulated execution - replace with real domain driver
        try:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return StepResult(
                step_id=step.id,
                status_code=200,
                headers={{"x-plugin": "{name_snake}", "action": action}},
                data={{"status": "ok", "action": action, "params": params}},
                duration_ms=duration_ms,
            )
        except Exception as e:
            return StepResult(
                step_id=step.id,
                status_code=None,
                transport_error=str(e),
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )
'''

TEMPLATE_OBSERVER = '''"""Observer contract implementation."""
from __future__ import annotations
from typing import Any
from cairn_test.contracts import (
    DiffChange,
    DiffKind,
    Observation,
    ObservationDiff,
    StepResult,
)

class {name_pascal}Observer:
    """Derives normalized structural observations and computes diffs."""

    def observe(self, result: StepResult) -> Observation:
        headers_list = list(result.headers.keys()) if result.headers else []
        body_data = result.data if isinstance(result.data, dict) else {{}}
        return Observation(
            status=result.status_code or 0,
            headers=headers_list,
            body_shape={{"keys": list(body_data.keys())}},
        )

    def compare(self, recorded: Observation, observed: Observation) -> ObservationDiff:
        changes: list[DiffChange] = []
        if recorded.status != observed.status:
            changes.append(
                DiffChange(
                    path="$.status",
                    kind=DiffKind.BREAKING,
                    recorded=recorded.status,
                    observed=observed.status,
                    detail=f"Status changed from {{recorded.status}} to {{observed.status}}",
                )
            )

        recorded_keys = set(recorded.body_shape.get("keys", [])) if isinstance(recorded.body_shape, dict) else set()
        observed_keys = set(observed.body_shape.get("keys", [])) if isinstance(observed.body_shape, dict) else set()

        # Added keys -> Additive diff
        for k in observed_keys - recorded_keys:
            changes.append(
                DiffChange(
                    path=f"$.{{k}}",
                    kind=DiffKind.ADDITIVE,
                    recorded=None,
                    observed=k,
                    detail=f"Field '{{k}}' added",
                )
            )

        # Removed keys -> Breaking diff
        for k in recorded_keys - observed_keys:
            changes.append(
                DiffChange(
                    path=f"$.{{k}}",
                    kind=DiffKind.BREAKING,
                    recorded=k,
                    observed=None,
                    detail=f"Field '{{k}}' removed",
                )
            )

        return ObservationDiff(changes=changes)

    def diff(self, recorded: Observation, observed: Observation) -> ObservationDiff:
        return self.compare(recorded, observed)
'''

TEMPLATE_FINGERPRINT = '''"""Fingerprinter contract implementation."""
from __future__ import annotations
import hashlib
import json
from typing import Any
from cairn_test.contracts import Fingerprint, ResolvedStep, RunContext

class {name_pascal}Fingerprinter:
    """Computes pre-execution hashes and touched operations for impact analysis."""

    def pre(self, step: ResolvedStep, ctx: RunContext) -> Fingerprint:
        raw = f"{{step.operation}}:{{json.dumps(step.params, sort_keys=True)}}"
        h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return Fingerprint(data={{"op_hash": h, "operation": step.operation}})

    def fingerprint(self, step: ResolvedStep, ctx: RunContext) -> Fingerprint:
        return self.pre(step, ctx)

    def touches(self, test: dict[str, Any], trace: dict[str, Any] | None) -> list[str]:
        ops: list[str] = []
        for step in test.get("steps", []):
            op = step.get("op") or step.get("operation") or step.get("id")
            if op:
                ops.append(op)
        return ops
'''

TEMPLATE_ASSERTIONS = '''"""AssertionType contract implementation."""
from __future__ import annotations
from typing import Any
from cairn_test.contracts import ResolvedStep, RunContext, StepResult

class {name_pascal}StatusAssertion:
    """Evaluates {name_snake}_status expectations."""
    name: str = "{name_snake}_status"

    def reads(self, spec: dict[str, Any]) -> list[str]:
        return ["$.status"]

    def evaluate(self, spec: dict[str, Any], result: StepResult, ctx: RunContext) -> bool | str:
        expected = spec.get(self.name, 200)
        return result.status_code == expected
'''

TEMPLATE_EVIDENCE = '''"""EvidenceCollector contract implementation."""
from __future__ import annotations
import json
from typing import Any
from cairn_test.contracts import Artifact, RunContext, StepResult

class {name_pascal}EvidenceCollector:
    """Collects and masks execution artifacts for persistent storage."""

    def collect(self, result: StepResult, ctx: RunContext) -> list[Artifact]:
        payload = {{
            "step_id": result.step_id,
            "status": result.status_code,
            "duration_ms": result.duration_ms,
            "data": result.data,
        }}
        return [
            Artifact(
                name=f"{{result.step_id}}_{name_snake}.json",
                media_type="application/json",
                content=json.dumps(payload, indent=2),
                masked=True,
            )
        ]
'''

TEMPLATE_TEST = '''"""
Assert-based test suite for {name_title} Plugin.
Verifies all 5 contracts against mock data without external test frameworks.
"""

import importlib
from pathlib import Path
import sys

# Ensure plugin parent directory and cairn-test repository are on sys.path
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(THIS_DIR.parent))

# Load plugin package
plugin_pkg = importlib.import_module(THIS_DIR.name)

from cairn_test.contracts import ResolvedStep, RunContext, DiffKind
from cairn_test.core.plugins import PluginRegistry

register_{name_snake}_plugin = plugin_pkg.register_{name_snake}_plugin
{name_pascal}StepExecutor = plugin_pkg.{name_pascal}StepExecutor
{name_pascal}Observer = plugin_pkg.{name_pascal}Observer
{name_pascal}Fingerprinter = plugin_pkg.{name_pascal}Fingerprinter
{name_pascal}StatusAssertion = plugin_pkg.{name_pascal}StatusAssertion
{name_pascal}EvidenceCollector = plugin_pkg.{name_pascal}EvidenceCollector

def run_tests() -> None:
    ctx = RunContext(run_id="test-run", worker_id="w-0", env_profile="local")
    step = ResolvedStep(
        id="s1",
        kind="{name_snake}",
        operation="ping",
        method="GET",
        path="/ping",
        params={{"key": "value"}},
    )

    # 1. StepExecutor Contract
    executor = {name_pascal}StepExecutor()
    res = executor.execute(step, ctx)
    assert res.step_id == "s1", "StepExecutor must preserve step_id"
    assert res.status_code == 200, f"Expected 200, got {{res.status_code}}"
    assert res.transport_error is None
    print("✓ StepExecutor contract verified")

    # 2. Observer Contract
    observer = {name_pascal}Observer()
    obs1 = observer.observe(res)
    assert obs1.status == 200
    assert "keys" in obs1.body_shape

    # Diff comparison
    obs2 = observer.observe(res)
    diff_same = observer.compare(obs1, obs2)
    assert not diff_same.has_breaking
    assert not diff_same.has_additive
    print("✓ Observer contract verified")

    # 3. Fingerprinter Contract
    fingerprinter = {name_pascal}Fingerprinter()
    fp = fingerprinter.pre(step, ctx)
    assert "op_hash" in fp.data
    touches = fingerprinter.touches({{"steps": [{{"op": "ping"}}]}}, None)
    assert touches == ["ping"]
    print("✓ Fingerprinter contract verified")

    # 4. AssertionType Contract
    assertion = {name_pascal}StatusAssertion()
    assert assertion.reads({{}}) == ["$.status"]
    assert assertion.evaluate({{"{name_snake}_status": 200}}, res, ctx) is True
    assert assertion.evaluate({{"{name_snake}_status": 404}}, res, ctx) is False
    print("✓ AssertionType contract verified")

    # 5. EvidenceCollector Contract
    collector = {name_pascal}EvidenceCollector()
    artifacts = collector.collect(res, ctx)
    assert len(artifacts) == 1
    assert artifacts[0].masked is True
    print("✓ EvidenceCollector contract verified")

    # 6. PluginRegistry Integration
    registry = PluginRegistry()
    register_{name_snake}_plugin(registry)
    assert "{name_snake}" in registry.step_executors
    assert "{name_snake}" in registry.observers
    assert "{name_snake}" in registry.fingerprinters
    assert "{name_snake}" in registry.evidence_collectors
    assert "{name_snake}_status" in registry.assertions
    print("✓ PluginRegistry registration verified")

    print("\\nAll {name_title} Plugin contracts successfully passed!")

if __name__ == "__main__":
    run_tests()
'''

TEMPLATE_README = '''# {name_title} Plugin for cairn-test

This plugin implements the 5 domain-neutral contracts for `cairn-test`:
- **StepExecutor**: Executes steps for kind `{name_snake}`.
- **Observer**: Normalizes outputs and computes structural diffs (`IDENTICAL`, `ADDITIVE`, `BREAKING`).
- **Fingerprinter**: Computes pre-execution hashes and maps touched operations for `cairn-test impact`.
- **AssertionType**: Implements `{name_snake}_status` expectations.
- **EvidenceCollector**: Captures masked execution logs into the event store.

## Running Contract Verification
Run the assert-based test suite with zero extra dependencies:
```bash
python test_{name_snake}_plugin.py
```

## Registering in your cairn-test Project
Add to your project's plugin loader:
```python
from cairn_test.core.plugins import default_registry
from plugins.{name_snake} import register_{name_snake}_plugin

register_{name_snake}_plugin(default_registry)
```
'''

def _to_snake(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower().strip("_")

def _to_pascal(snake: str) -> str:
    return "".join(word.capitalize() for word in snake.split("_"))

def scaffold_plugin(plugin_name: str, target_dir: Path | None = None) -> dict[str, Any]:
    """Scaffold a new cairn-test domain plugin."""
    snake_name = _to_snake(plugin_name)
    if not snake_name:
        raise ValueError(f"Invalid plugin name: '{plugin_name}'")

    pascal_name = _to_pascal(snake_name)
    title_name = snake_name.replace("_", " ").title()

    if target_dir is None:
        target_dir = Path("plugins") / snake_name
    else:
        target_dir = Path(target_dir).resolve()

    target_dir.mkdir(parents=True, exist_ok=True)

    # Determine module import path for test
    module_import = f"plugins.{snake_name}" if "plugins" in target_dir.parts else snake_name

    files = {
        target_dir / "__init__.py": TEMPLATE_INIT.format(
            name_snake=snake_name,
            name_pascal=pascal_name,
            name_title=title_name,
        ),
        target_dir / "executor.py": TEMPLATE_EXECUTOR.format(
            name_snake=snake_name,
            name_pascal=pascal_name,
            name_title=title_name,
        ),
        target_dir / "observer.py": TEMPLATE_OBSERVER.format(
            name_snake=snake_name,
            name_pascal=pascal_name,
            name_title=title_name,
        ),
        target_dir / "fingerprint.py": TEMPLATE_FINGERPRINT.format(
            name_snake=snake_name,
            name_pascal=pascal_name,
            name_title=title_name,
        ),
        target_dir / "assertions.py": TEMPLATE_ASSERTIONS.format(
            name_snake=snake_name,
            name_pascal=pascal_name,
            name_title=title_name,
        ),
        target_dir / "evidence.py": TEMPLATE_EVIDENCE.format(
            name_snake=snake_name,
            name_pascal=pascal_name,
            name_title=title_name,
        ),
        target_dir / f"test_{snake_name}_plugin.py": TEMPLATE_TEST.format(
            name_snake=snake_name,
            name_pascal=pascal_name,
            name_title=title_name,
            module_import=module_import,
        ),
        target_dir / "README.md": TEMPLATE_README.format(
            name_snake=snake_name,
            name_pascal=pascal_name,
            name_title=title_name,
        ),
    }

    created_paths: list[str] = []
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
        created_paths.append(str(path))

    return {
        "status": "created",
        "plugin": snake_name,
        "directory": str(target_dir),
        "files": created_paths,
    }
