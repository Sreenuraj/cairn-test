"""
Minimal trace writer for API plugin (T2.7, FR-R2 partial).

Executes hand-written test definitions against a target API and records valid cairn-test.trace/v1 traces.
"""

from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
import yaml

from cairn_test.contracts import ResolvedStep, RunContext
from cairn_test.core.schemas import load_trace
from cairn_test.plugins.api.http import HttpStepExecutor
from cairn_test.plugins.api.jsonpath import extract_jsonpath
from cairn_test.plugins.api.observer import ApiObserver
from cairn_test.plugins.api.spec import OpenAPISpec

def compute_step_hash(step_spec: dict[str, Any]) -> str:
    """Computes SHA-256 hash of a step definition."""
    b = json.dumps(step_spec, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b).hexdigest()

def record_test_trace(
    test_def: dict[str, Any],
    spec: OpenAPISpec | None = None,
    base_url: str = "",
    env_profile: str = "local",
    output_dir: Path | str = "traces",
) -> Path:
    test_id = test_def["id"]
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    executor = HttpStepExecutor(spec=spec, base_url=base_url)
    observer = ApiObserver()
    ctx = RunContext(run_id="record-session", worker_id="w-rec", env_profile=env_profile)

    trace_steps: list[dict[str, Any]] = []

    for step_spec in test_def.get("steps", []):
        step_id = step_spec["id"]
        op_id = step_spec.get("op", step_id)

        # Lookup operation definition from spec if available
        op_def = None
        method = "GET"
        path = f"/{op_id}"
        op_hash = hashlib.sha256(op_id.encode("utf-8")).hexdigest()

        if spec:
            try:
                op_def = spec.get_operation(op_id)
                method = op_def.method
                path = op_def.path
                op_hash = op_def.op_hash
            except KeyError:
                pass

        from cairn_test.core.scheduler import interpolate
        resolved_args = interpolate(step_spec.get("args", {}), ctx.variables)
        resolved_auth = interpolate(step_spec.get("auth"), ctx.variables) if step_spec.get("auth") else None
        step_headers = {str(k): str(v) for k, v in resolved_args.get("headers", {}).items()} if isinstance(resolved_args, dict) else {}

        resolved_step = ResolvedStep(
            id=step_id,
            kind="http",
            operation=op_id,
            method=method,
            path=path,
            params=resolved_args if isinstance(resolved_args, dict) else {},
            headers=step_headers,
            body=resolved_args.get("body") if isinstance(resolved_args, dict) and "body" in resolved_args else resolved_args,
            auth=resolved_auth,
            timeout_ms=step_spec.get("timeout_ms", 10000),
        )

        res = executor.execute(resolved_step, ctx)
        obs = observer.observe(res)

        # Variable extraction for multi-step tests
        for var_name, jpath in step_spec.get("extract", {}).items():
            val = extract_jsonpath(res.data, jpath)
            if val is not None:
                ctx.variables[var_name] = val

        trace_step = {
            "id": step_id,
            "step_hash": compute_step_hash(step_spec),
            "resolved": {
                "operation": op_id,
                "method": method,
                "path": path,
                "params": resolved_step.params,
                "headers": step_headers,
            },
            "pre_fingerprint": {"op_hash": op_hash},
            "observation": {
                "status": obs.status,
                "headers": obs.headers,
                "body_shape": obs.body_shape,
            },
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        trace_steps.append(trace_step)

    trace_doc = {
        "schema": "cairn-test.trace/v1",
        "test": test_id,
        "env_profile": env_profile,
        "spec_hash": spec.spec_hash if spec else "0" * 64,
        "steps": trace_steps,
    }

    # Validate against schema before saving
    load_trace(trace_doc)

    out_file = out_dir / f"{test_id}.trace.yaml"
    with open(out_file, "w", encoding="utf-8") as f:
        yaml.dump(trace_doc, f, sort_keys=False)

    return out_file
