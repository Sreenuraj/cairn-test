"""
Plugin registry and invocation wrappers (T1.4, FR-P2, FR-P3).

Enforces:
- Plugins return data only, never outcomes.
- Core wraps all plugin invocations and emits structured lifecycle events.
- Extensibility: new step and assertion types register dynamically without core code modifications.
"""

from __future__ import annotations
import time
from typing import Any
from cairn_test.contracts import (
    StepExecutor,
    Observer,
    Fingerprinter,
    AssertionType,
    Healer,
    EvidenceCollector,
    SessionProvider,
    ResolvedStep,
    StepResult,
    Observation,
    ObservationDiff,
    RunContext,
)
from cairn_test.core.events import EventBus, EventStore

class PluginRegistry:
    """Registry for step executors, observers, fingerprinters, assertion types, healers, and evidence collectors."""

    def __init__(self):
        self.step_executors: dict[str, StepExecutor] = {}
        self.observers: dict[str, Observer] = {}
        self.fingerprinters: dict[str, Fingerprinter] = {}
        self.assertions: dict[str, AssertionType] = {}
        self.healers: dict[str, Healer] = {}
        self.evidence_collectors: dict[str, EvidenceCollector] = {}
        self.session_providers: dict[str, SessionProvider] = {}
        self.versions: dict[str, str] = {}

    def register_step_executor(self, kind: str, executor: StepExecutor, version: str = "0.1.0") -> None:
        self.step_executors[kind] = executor
        self.versions[kind] = version

    def register_observer(self, kind: str, observer: Observer) -> None:
        self.observers[kind] = observer

    def register_fingerprinter(self, kind: str, fingerprinter: Fingerprinter) -> None:
        self.fingerprinters[kind] = fingerprinter

    def register_assertion(self, name: str, assertion: AssertionType) -> None:
        self.assertions[name] = assertion

    def register_healer(self, kind: str, healer: Healer) -> None:
        self.healers[kind] = healer

    def register_evidence_collector(self, kind: str, collector: EvidenceCollector) -> None:
        self.evidence_collectors[kind] = collector

    def register_session_provider(self, kind: str, provider: SessionProvider) -> None:
        self.session_providers[kind] = provider

    def get_step_executor(self, kind: str) -> StepExecutor:
        if kind not in self.step_executors:
            raise KeyError(f"No step executor registered for kind '{kind}'")
        return self.step_executors[kind]

    def get_observer(self, kind: str) -> Observer:
        if kind not in self.observers:
            raise KeyError(f"No observer registered for kind '{kind}'")
        return self.observers[kind]

    def get_fingerprinter(self, kind: str) -> Fingerprinter:
        if kind not in self.fingerprinters:
            raise KeyError(f"No fingerprinter registered for kind '{kind}'")
        return self.fingerprinters[kind]

    def get_assertion(self, name: str) -> AssertionType:
        if name not in self.assertions:
            raise KeyError(f"No assertion type registered for name '{name}'")
        return self.assertions[name]

    def get_healer(self, kind: str) -> Healer | None:
        return self.healers.get(kind)

    def get_evidence_collector(self, kind: str) -> EvidenceCollector | None:
        return self.evidence_collectors.get(kind)

    def get_session_provider(self, kind: str) -> SessionProvider | None:
        return self.session_providers.get(kind)

class PluginWrapper:
    """Wraps plugin calls to capture metrics, store evidence, and emit lifecycle events."""

    def __init__(self, registry: PluginRegistry, event_bus: EventBus, store: EventStore | None = None):
        self.registry = registry
        self.event_bus = event_bus
        self.store = store

    def execute_step(self, step: ResolvedStep, ctx: RunContext) -> StepResult:
        executor = self.registry.get_step_executor(step.kind)
        start_t = time.perf_counter()
        try:
            result = executor.execute(step, ctx)
        except Exception as exc:
            duration = (time.perf_counter() - start_t) * 1000.0
            result = StepResult(
                step_id=step.id,
                status_code=None,
                duration_ms=duration,
                transport_error=f"Uncaught exception in executor '{step.kind}': {exc}",
            )
        else:
            if result.duration_ms <= 0:
                result.duration_ms = (time.perf_counter() - start_t) * 1000.0

        # Collect evidence if collector registered
        collector = self.registry.get_evidence_collector(step.kind)
        if collector and self.store:
            try:
                artifacts = collector.collect(result, ctx)
                for art in artifacts:
                    self.store.store_artifact(
                        ctx.run_id,
                        f"{step.id}_{art.name}",
                        art.content,
                        media_type=art.media_type,
                    )
            except Exception:
                pass

        # Emit step.executed event
        self.event_bus.emit("step.executed", {
            "step_id": step.id,
            "kind": step.kind,
            "status_code": result.status_code,
            "duration_ms": result.duration_ms,
            "transport_error": result.transport_error,
        })
        return result

    def observe_and_diff(
        self,
        kind: str,
        step_id: str,
        recorded_obs: Observation | None,
        result: StepResult,
    ) -> tuple[Observation, ObservationDiff]:
        observer = self.registry.get_observer(kind)
        observed = observer.observe(result)

        if recorded_obs is None:
            # No prior recording
            diff = ObservationDiff()
        else:
            diff = observer.compare(recorded_obs, observed)

        # Emit observation.diffed event
        self.event_bus.emit("observation.diffed", {
            "step_id": step_id,
            "has_breaking": diff.has_breaking,
            "has_additive": diff.has_additive,
            "changes": [
                {
                    "path": c.path,
                    "kind": c.kind.value,
                    "recorded": c.recorded,
                    "observed": c.observed,
                    "detail": c.detail,
                }
                for c in diff.changes
            ],
        })
        return observed, diff
