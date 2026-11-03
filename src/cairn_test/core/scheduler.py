"""
Scheduler and worker execution engine for cairn-test core (T1.8, FR-C4, FR-C18, FR-C12).

Handles:
- Per-worker data isolation built-ins: {run.uid}, {worker.id}
- Parallel execution for hermetic tests with configurable concurrency
- Serial execution for hermetic: false tests
- Variable resolution, interpolation, and step extraction
- Lifecycle orchestration and result recording
"""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import re
import time
from typing import Any
import uuid

from cairn_test.contracts import (
    Observation,
    ResolvedStep,
    RunContext,
    StepResult,
)
from cairn_test.core.events import EventBus, EventStore, FRAMEWORK_VERSION
from cairn_test.core.expectations import EvaluatedExpectation, evaluate_expectation
from cairn_test.core.outcome import TestVerdict, decide_outcome
from cairn_test.core.planner import PlanItem
from cairn_test.core.plugins import PluginRegistry, PluginWrapper

VAR_PATTERN = re.compile(r"\{([a-zA-Z0-9_.-]+)\}")

def interpolate(target: Any, variables: dict[str, Any]) -> Any:
    """Recursively replaces {var_name} templates in strings, dicts, and lists."""
    if isinstance(target, str):
        def repl(match: re.Match) -> str:
            key = match.group(1)
            val = variables.get(key, match.group(0))
            return str(val)
        # If the string is purely "{key}" and key exists, return original typed value
        m = VAR_PATTERN.fullmatch(target)
        if m:
            key = m.group(1)
            if key in variables:
                return variables[key]
        return VAR_PATTERN.sub(repl, target)
    elif isinstance(target, dict):
        return {k: interpolate(v, variables) for k, v in target.items()}
    elif isinstance(target, list):
        return [interpolate(v, variables) for v in target]
    return target

class Worker:
    """Executes a single test inside an isolated context."""

    def __init__(
        self,
        worker_id: str,
        run_id: str,
        env_profile: str,
        registry: PluginRegistry,
        event_bus: EventBus,
        store: EventStore | None = None,
        default_timeout_ms: int = 10000,
    ):
        self.worker_id = worker_id
        self.run_id = run_id
        self.env_profile = env_profile
        self.registry = registry
        self.event_bus = event_bus
        self.store = store
        self.wrapper = PluginWrapper(registry, event_bus, store)
        self.default_timeout_ms = default_timeout_ms

    def execute_test(
        self,
        item: PlanItem,
        recorded_trace: dict[str, Any] | None = None,
        verification_status: str = "valid",
        verification_reason: str | None = None,
    ) -> TestVerdict:
        test_id = item.test_id
        start_t = time.perf_counter()

        # Handle skipped tests from planner
        if item.action == "SKIPPED":
            verdict = decide_outcome(
                planned="SKIPPED",
                skip_reason=item.reason,
                verification=verification_status,
                verification_reason=verification_reason,
            )
            self._record_verdict(test_id, verdict, duration_ms=0.0)
            return verdict

        # Handle strict mode verification failure
        if verification_status != "valid":
            verdict = decide_outcome(
                planned="EXECUTE",
                verification=verification_status,
                verification_reason=verification_reason,
            )
            self._record_verdict(test_id, verdict, duration_ms=0.0)
            return verdict

        # Build execution context and isolated variables
        run_uid = self.run_id.split("-")[-1] if "-" in self.run_id else self.run_id[:8]
        variables: dict[str, Any] = {
            "run.uid": run_uid,
            "worker.id": self.worker_id,
        }

        # Resolve test.data variables
        raw_data = item.test_def.get("data", {})
        for k, v in raw_data.items():
            variables[k] = interpolate(v, variables)

        ctx = RunContext(
            run_id=self.run_id,
            worker_id=self.worker_id,
            env_profile=self.env_profile,
            variables=variables,
        )

        steps_info: list[dict[str, Any]] = []
        evaluated_exps: list[EvaluatedExpectation] = []
        step_results: dict[str, StepResult] = {}
        blocked_by_step: str | None = None
        blocking_cause: str | None = None

        trace_steps_map: dict[str, dict[str, Any]] = {}
        if recorded_trace:
            for s in recorded_trace.get("steps", []):
                trace_steps_map[s["id"]] = s

        # Execute test steps sequentially
        for step_spec in item.test_def.get("steps", []):
            step_id = step_spec["id"]
            rec_step = trace_steps_map.get(step_id, {})
            step_kind = step_spec.get("kind", "http")

            # Check if this step is blocked by an earlier step
            if blocked_by_step:
                steps_info.append({
                    "id": step_id,
                    "blocked_by": blocked_by_step,
                    "transport_error": None,
                    "pre_fingerprint_match": True,
                    "observation_diff": {},
                })
                continue

            # Resolve step arguments and parameters
            resolved_args = interpolate(step_spec.get("args", {}), ctx.variables)
            resolved_auth = interpolate(step_spec.get("auth"), ctx.variables) if step_spec.get("auth") else None

            # Pre-fingerprint check
            pre_fingerprint_match = True
            fingerprinter = None
            try:
                fingerprinter = self.registry.get_fingerprinter(step_kind)
            except KeyError:
                pass

            step_body = resolved_args.get("body") if (isinstance(resolved_args, dict) and "body" in resolved_args) else resolved_args
            step_params = resolved_args if isinstance(resolved_args, dict) else rec_step.get("resolved", {}).get("params", {})

            resolved = ResolvedStep(
                id=step_id,
                kind=step_kind,
                operation=step_spec.get("op", step_id),
                method=rec_step.get("resolved", {}).get("method", "POST"),
                path=rec_step.get("resolved", {}).get("path", f"/{step_spec.get('op', step_id)}"),
                params=step_params,
                headers=rec_step.get("resolved", {}).get("headers", {}),
                body=step_body,
                auth=resolved_auth,
                timeout_ms=step_spec.get("timeout_ms", self.default_timeout_ms),
            )

            if fingerprinter and "pre_fingerprint" in rec_step:
                try:
                    current_fp = fingerprinter.pre(resolved, ctx)
                    rec_fp = rec_step["pre_fingerprint"]
                    pre_fingerprint_match = (current_fp.data == rec_fp)
                except Exception:
                    pre_fingerprint_match = False

            # Execute step via plugin wrapper
            step_result = self.wrapper.execute_step(resolved, ctx)
            step_results[step_id] = step_result

            # Extract variables from result if configured
            extract_map = step_spec.get("extract", {})
            extraction_failed = False
            for var_name, jpath in extract_map.items():
                val = self._extract_jsonpath(step_result.data, jpath)
                if val is not None:
                    ctx.variables[var_name] = val
                else:
                    extraction_failed = True

            # If transport error or missing extracted variable, subsequent steps are blocked
            if step_result.transport_error:
                blocked_by_step = step_id
                blocking_cause = "ERROR"
            elif extraction_failed and extract_map:
                blocked_by_step = step_id
                blocking_cause = "DRIFT"

            # Observe and diff
            rec_obs_data = rec_step.get("observation")
            rec_obs = None
            if rec_obs_data:
                rec_obs = Observation(
                    status=rec_obs_data["status"],
                    headers=rec_obs_data.get("headers", []),
                    body_shape=rec_obs_data.get("body_shape"),
                )

            obs, diff = self.wrapper.observe_and_diff(step_kind, step_id, rec_obs, step_result)

            steps_info.append({
                "id": step_id,
                "transport_error": step_result.transport_error,
                "pre_fingerprint_match": pre_fingerprint_match,
                "observation_diff": {
                    "breaking_paths": [c.path for c in diff.changes if c.kind.value == "breaking"],
                    "additive_paths": [c.path for c in diff.changes if c.kind.value == "additive"],
                },
            })

        # Evaluate expectations
        for idx, exp_spec in enumerate(item.test_def.get("expect", [])):
            exp_id = f"exp-{idx}"
            after_step = exp_spec.get("after") or (item.test_def["steps"][-1]["id"] if item.test_def.get("steps") else "")
            
            # Find assertion type plugin if registered dynamically
            assertion_type = None
            for key in exp_spec:
                if key != "after":
                    try:
                        assertion_type = self.registry.get_assertion(key)
                        break
                    except KeyError:
                        pass

            # Find matching step information
            st_info = next((s for s in steps_info if s["id"] == after_step), None)
            st_result = step_results.get(after_step)
            st_blocked = st_info.get("blocked_by") if st_info else None

            # Reconstruct ObservationDiff
            obs_diff = None
            if st_info and "observation_diff" in st_info:
                from cairn_test.contracts import DiffChange, DiffKind, ObservationDiff
                ch = []
                for bp in st_info["observation_diff"].get("breaking_paths", []):
                    ch.append(DiffChange(path=bp, kind=DiffKind.BREAKING, recorded=None, observed=None))
                for ap in st_info["observation_diff"].get("additive_paths", []):
                    ch.append(DiffChange(path=ap, kind=DiffKind.ADDITIVE, recorded=None, observed=None))
                obs_diff = ObservationDiff(changes=ch)

            eval_res = evaluate_expectation(
                exp_spec=exp_spec,
                exp_id=exp_id,
                step_id=after_step,
                assertion_type=assertion_type,
                step_result=st_result,
                obs_diff=obs_diff,
                blocked_by=st_blocked,
                blocking_cause=blocking_cause,
                ctx=ctx,
            )
            evaluated_exps.append(eval_res)

        # Decide final test verdict
        verdict = decide_outcome(
            planned=item.action,
            steps_info=steps_info,
            expectations=evaluated_exps,
        )

        duration_ms = (time.perf_counter() - start_t) * 1000.0
        self._record_verdict(test_id, verdict, duration_ms)
        return verdict

    def _extract_jsonpath(self, data: Any, path: str) -> Any:
        if data is None or not isinstance(data, dict):
            return None
        # Minimal native extractor for $.field and $.field.sub
        p = path.strip()
        if p.startswith("$."):
            p = p[2:]
        elif p.startswith("$"):
            p = p[1:]
        parts = p.split(".")
        curr = data
        for part in parts:
            if isinstance(curr, dict) and part in curr:
                curr = curr[part]
            else:
                return None
        return curr

    def _record_verdict(self, test_id: str, verdict: TestVerdict, duration_ms: float) -> None:
        now_utc = datetime.now(timezone.utc).isoformat()
        
        # Emit test.finished event
        self.event_bus.emit("test.finished", {
            "test_id": test_id,
            "outcome": verdict.outcome,
            "duration_ms": duration_ms,
            "reason": verdict.reason,
            "has_drift_detail": verdict.has_drift_detail,
        })

        # Save result document
        if self.store:
            res_doc = {
                "schema": "cairn-test.result/v1",
                "run_id": self.run_id,
                "test": test_id,
                "outcome": verdict.outcome,
                "duration_ms": duration_ms,
                "reason": verdict.reason or "",
                "drift_detail": verdict.drift_detail,
                "expectations": [
                    {
                        "after": e.step_id,
                        "kind": e.kind,
                        "value": e.value,
                        "reason": e.reason or "",
                    }
                    for e in verdict.expectations
                ],
                "versions": {
                    "framework": FRAMEWORK_VERSION,
                    "plugins": dict(self.registry.versions),
                },
                "recorded_at": now_utc,
            }
            self.store.record_result(res_doc)

class Scheduler:
    """Schedules hermetic tests in parallel and non-hermetic tests serially."""

    def __init__(
        self,
        run_id: str,
        env_profile: str,
        registry: PluginRegistry,
        event_bus: EventBus,
        store: EventStore | None = None,
        parallelism: int = 4,
        default_timeout_ms: int = 10000,
    ):
        self.run_id = run_id
        self.env_profile = env_profile
        self.registry = registry
        self.event_bus = event_bus
        self.store = store
        self.parallelism = max(1, parallelism)
        self.default_timeout_ms = default_timeout_ms

    def run_suite(
        self,
        planned_items: list[PlanItem],
        traces: dict[str, dict[str, Any]] | None = None,
        verification_status: str | dict[str, Any] = "valid",
    ) -> list[TestVerdict]:
        traces_map = traces or {}
        
        def get_v_status(tid: str) -> tuple[str, str | None]:
            if isinstance(verification_status, dict):
                val = verification_status.get(tid, "valid")
                if isinstance(val, tuple):
                    return val[0], val[1]
                return val, val if val != "valid" else None
            return verification_status, None

        # Partition into hermetic (parallel) and non-hermetic (serial)
        hermetic_items: list[PlanItem] = []
        serial_items: list[PlanItem] = []

        for item in planned_items:
            if item.hermetic:
                hermetic_items.append(item)
            else:
                serial_items.append(item)

        results_by_id: dict[str, TestVerdict] = {}

        # 1. Execute hermetic tests with worker pool
        if hermetic_items:
            with ThreadPoolExecutor(max_workers=self.parallelism) as executor:
                futures = {}
                for idx, item in enumerate(hermetic_items):
                    worker = Worker(
                        worker_id=f"worker-{idx % self.parallelism}",
                        run_id=self.run_id,
                        env_profile=self.env_profile,
                        registry=self.registry,
                        event_bus=self.event_bus,
                        store=self.store,
                        default_timeout_ms=self.default_timeout_ms,
                    )
                    v_stat, v_reas = get_v_status(item.test_id)
                    fut = executor.submit(
                        worker.execute_test,
                        item,
                        recorded_trace=traces_map.get(item.test_id),
                        verification_status=v_stat,
                        verification_reason=v_reas,
                    )
                    futures[fut] = item

                for fut in as_completed(futures):
                    item = futures[fut]
                    results_by_id[item.test_id] = fut.result()

        # 2. Execute non-hermetic tests strictly serially
        serial_worker = Worker(
            worker_id="worker-serial",
            run_id=self.run_id,
            env_profile=self.env_profile,
            registry=self.registry,
            event_bus=self.event_bus,
            store=self.store,
            default_timeout_ms=self.default_timeout_ms,
        )
        for item in serial_items:
            v_stat, v_reas = get_v_status(item.test_id)
            verdict = serial_worker.execute_test(
                item,
                recorded_trace=traces_map.get(item.test_id),
                verification_status=v_stat,
                verification_reason=v_reas,
            )
            results_by_id[item.test_id] = verdict

        # Return verdicts strictly in planned order
        return [results_by_id[item.test_id] for item in planned_items]
