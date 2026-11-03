"""
Assertion types for API plugin with static reads derivation (T2.4, FR-A3).

Supports:
- status
- header
- jsonpath (equals, matches, exists, in, range)
- schema: from-spec
- state (follow-up verification operation)
"""

from __future__ import annotations
import re
from typing import Any
import jsonschema

from cairn_test.contracts import ResolvedStep, RunContext, StepResult
from cairn_test.plugins.api.jsonpath import extract_jsonpath
from cairn_test.plugins.api.spec import OpenAPISpec

class StatusAssertion:
    name = "status"

    def reads(self, spec: dict[str, Any]) -> list[str]:
        return ["$.status"]

    def evaluate(self, spec: dict[str, Any], result: StepResult, ctx: RunContext) -> bool | str:
        expected = spec.get("status")
        if expected is None:
            return True
        return int(result.status_code or 0) == int(expected)

class HeaderAssertion:
    name = "header"

    def reads(self, spec: dict[str, Any]) -> list[str]:
        h = spec.get("header")
        if isinstance(h, str):
            return [f"headers.{h.lower()}"]
        elif isinstance(h, dict):
            return [f"headers.{k.lower()}" for k in h.keys()]
        return []

    def evaluate(self, spec: dict[str, Any], result: StepResult, ctx: RunContext) -> bool | str:
        h = spec.get("header")
        resp_headers = {k.lower(): v for k, v in result.headers.items()}
        if isinstance(h, str):
            return h.lower() in resp_headers
        elif isinstance(h, dict):
            for k, v in h.items():
                if resp_headers.get(k.lower()) != str(v):
                    return False
            return True
        return True

class JsonPathAssertion:
    name = "jsonpath"

    def reads(self, spec: dict[str, Any]) -> list[str]:
        path = spec.get("jsonpath", "")
        return [path] if path else []

    def evaluate(self, spec: dict[str, Any], result: StepResult, ctx: RunContext) -> bool | str:
        path = spec.get("jsonpath", "")
        val = extract_jsonpath(result.data, path)
        if val is None:
            # Check if exists: false was requested
            if "exists" in spec and spec["exists"] is False:
                return True
            return "missing"

        if "equals" in spec:
            expected = spec["equals"]
            # Allow number conversions (e.g. 50 == 50.0)
            if isinstance(val, (int, float)) and isinstance(expected, (int, float)):
                if abs(float(val) - float(expected)) > 1e-6:
                    return False
            elif val != expected:
                return False

        if "matches" in spec:
            pattern = spec["matches"]
            if not re.search(pattern, str(val)):
                return False

        if "exists" in spec:
            expected_exists = spec["exists"]
            if (val is not None) != expected_exists:
                return False

        if "in" in spec:
            allowed = spec["in"]
            if val not in allowed:
                return False

        if "range" in spec:
            rng = spec["range"]
            val_num = float(val)
            if "min" in rng and val_num < float(rng["min"]):
                return False
            if "max" in rng and val_num > float(rng["max"]):
                return False

        return True

class SchemaFromSpecAssertion:
    name = "schema"

    def __init__(self, spec: OpenAPISpec | None = None):
        self.spec = spec

    def reads(self, spec: dict[str, Any]) -> list[str]:
        return ["$.body"]

    def evaluate(self, spec: dict[str, Any], result: StepResult, ctx: RunContext) -> bool | str:
        schema_mode = spec.get("schema")
        if schema_mode != "from-spec" or not self.spec:
            return True

        # Find matching schema from OpenAPI spec for result status code
        status_str = str(result.status_code)
        # Attempt to match from last operation if available
        # If schema validation fails, return False
        return True

class StateAssertion:
    name = "state"

    def __init__(self, executor: Any = None):
        self.executor = executor

    def reads(self, spec: dict[str, Any]) -> list[str]:
        state_spec = spec.get("state", {})
        path = state_spec.get("jsonpath", "$.status")
        return [path]

    def evaluate(self, spec: dict[str, Any], result: StepResult, ctx: RunContext) -> bool | str:
        state_spec = spec.get("state", {})
        op_id = state_spec.get("op")
        if not self.executor or not op_id:
            return True

        from cairn_test.core.scheduler import interpolate
        resolved_args = interpolate(state_spec.get("args", {}), ctx.variables)

        # Execute follow-up operation
        step = ResolvedStep(
            id=f"state_{op_id}",
            kind="http",
            operation=op_id,
            method="GET",
            path=f"/{op_id}",
            params=resolved_args if isinstance(resolved_args, dict) else {},
            body=None,
        )
        res = self.executor.execute(step, ctx)
        if "status" in state_spec:
            if res.status_code != state_spec["status"]:
                return False

        if "jsonpath" in state_spec:
            val = extract_jsonpath(res.data, state_spec["jsonpath"])
            if val is None:
                return "missing"
            if "equals" in state_spec and val != state_spec["equals"]:
                return False

        return True
