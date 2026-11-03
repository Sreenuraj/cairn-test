"""
Fake plugin for cairn-test core (T1.9, FR-C10).

Allows tests to deterministically script:
- Every outcome (PASS, FAIL, DRIFT, ERROR, SKIPPED)
- Every expectation value (true, false, unevaluable, blocked)
- Every compound case from plan.md section 6.3
"""

from __future__ import annotations
from typing import Any
from cairn_test.contracts import (
    Artifact,
    AssertionType,
    DiffChange,
    DiffKind,
    EvidenceCollector,
    Fingerprint,
    Fingerprinter,
    Observation,
    ObservationDiff,
    Observer,
    ResolvedStep,
    RunContext,
    StepExecutor,
    StepResult,
)
from cairn_test.core.plugins import PluginRegistry

class FakeStepExecutor:
    kind = "fake"

    def execute(self, step: ResolvedStep, ctx: RunContext) -> StepResult:
        args = step.body if isinstance(step.body, dict) else (step.params or {})
        if not isinstance(args, dict):
            args = {}

        t_err = args.get("transport_error")
        status = args.get("status", 200)
        data = args.get("data", {})
        duration = float(args.get("duration_ms", 1.0))

        return StepResult(
            step_id=step.id,
            status_code=None if t_err else status,
            data=data,
            duration_ms=duration,
            transport_error=t_err,
        )

class FakeObserver:
    def observe(self, result: StepResult) -> Observation:
        body_shape = {}
        if isinstance(result.data, dict):
            body_shape = {k: type(v).__name__ for k, v in result.data.items()}
        return Observation(
            status=result.status_code or 0,
            headers=["content-type"],
            body_shape=body_shape,
        )

    def compare(self, recorded: Observation, observed: Observation) -> ObservationDiff:
        # Check if observed data specifies scripted diff overrides
        changes: list[DiffChange] = []
        if isinstance(observed.body_shape, dict) and "_diff" in observed.body_shape:
            # Scripted diff from step data
            pass

        # Status breaking change
        if recorded.status != observed.status:
            changes.append(
                DiffChange(
                    path="$.status",
                    kind=DiffKind.BREAKING,
                    recorded=recorded.status,
                    observed=observed.status,
                    detail=f"Status changed from {recorded.status} to {observed.status}",
                )
            )

        # Body shape key comparison
        rec_shape = recorded.body_shape if isinstance(recorded.body_shape, dict) else {}
        obs_shape = observed.body_shape if isinstance(observed.body_shape, dict) else {}

        # Removed keys -> breaking
        for k in rec_shape:
            if k not in obs_shape:
                changes.append(
                    DiffChange(
                        path=f"$.{k}",
                        kind=DiffKind.BREAKING,
                        recorded=rec_shape[k],
                        observed=None,
                        detail=f"Field '{k}' removed",
                    )
                )
            elif rec_shape[k] != obs_shape[k]:
                changes.append(
                    DiffChange(
                        path=f"$.{k}",
                        kind=DiffKind.BREAKING,
                        recorded=rec_shape[k],
                        observed=obs_shape[k],
                        detail=f"Field '{k}' type changed",
                    )
                )

        # Added keys -> additive
        for k in obs_shape:
            if k not in rec_shape:
                changes.append(
                    DiffChange(
                        path=f"$.{k}",
                        kind=DiffKind.ADDITIVE,
                        recorded=None,
                        observed=obs_shape[k],
                        detail=f"Field '{k}' added",
                    )
                )

        return ObservationDiff(changes=changes)

class FakeFingerprinter:
    def pre(self, step: ResolvedStep, ctx: RunContext) -> Fingerprint:
        args = step.body if isinstance(step.body, dict) else {}
        hash_val = args.get("op_hash", f"hash-{step.operation}")
        return Fingerprint(data={"op_hash": hash_val})

    def touches(self, test: dict[str, Any], trace: dict[str, Any] | None) -> list[str]:
        return [s.get("op", s["id"]) for s in test.get("steps", [])]

class FakeAssertion:
    name = "fake"

    def reads(self, spec: dict[str, Any]) -> list[str]:
        fake_spec = spec.get("fake", {})
        return fake_spec.get("reads", ["$.status"])

    def evaluate(self, spec: dict[str, Any], result: StepResult, ctx: RunContext) -> bool | str:
        fake_spec = spec.get("fake", {})
        val = fake_spec.get("evaluate", True)
        return val

class FakeEvidenceCollector:
    def collect(self, result: StepResult, ctx: RunContext) -> list[Artifact]:
        return [
            Artifact(
                name="step_trace.json",
                media_type="application/json",
                content=f'{{"step": "{result.step_id}", "status": {result.status_code}}}',
            )
        ]

def register_fake_plugin(registry: PluginRegistry) -> None:
    """Register all components of the fake plugin."""
    registry.register_step_executor("fake", FakeStepExecutor(), version="0.1.0")
    registry.register_observer("fake", FakeObserver())
    registry.register_fingerprinter("fake", FakeFingerprinter())
    registry.register_assertion("fake", FakeAssertion())
    registry.register_evidence_collector("fake", FakeEvidenceCollector())
