"""
Language-neutral plugin contracts for cairn-test.

Invariants:
1. Plugins return DATA only, never outcomes. The core outcome engine decides true/false/unevaluable and verdicts.
2. Plugins NEVER write to the event bus or manipulate approvals.
3. Plugins NEVER invent synthetic values or modify expectations.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

class DiffKind(str, Enum):
    IDENTICAL = "identical"
    ADDITIVE = "additive"
    BREAKING = "breaking"

@dataclass(frozen=True)
class DiffChange:
    path: str
    kind: DiffKind
    recorded: Any
    observed: Any
    detail: str = ""

@dataclass
class RunContext:
    run_id: str
    worker_id: str
    env_profile: str
    variables: dict[str, Any] = field(default_factory=dict)
    session: Any | None = None

@dataclass
class ResolvedStep:
    id: str
    kind: str
    operation: str
    method: str
    path: str
    params: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: Any | None = None
    auth: str | None = None
    timeout_ms: int = 5000

@dataclass
class StepResult:
    step_id: str
    status_code: int | None
    headers: dict[str, str] = field(default_factory=dict)
    data: Any | None = None
    duration_ms: float = 0.0
    transport_error: str | None = None

@dataclass
class Observation:
    status: int
    headers: list[str] = field(default_factory=list)
    body_shape: Any = None

@dataclass
class ObservationDiff:
    changes: list[DiffChange] = field(default_factory=list)

    @property
    def has_breaking(self) -> bool:
        return any(c.kind == DiffKind.BREAKING for c in self.changes)

    @property
    def has_additive(self) -> bool:
        return any(c.kind == DiffKind.ADDITIVE for c in self.changes)

@dataclass
class Fingerprint:
    data: dict[str, str] = field(default_factory=dict)

@dataclass
class Artifact:
    name: str
    media_type: str
    content: bytes | str
    masked: bool = True

@runtime_checkable
class StepExecutor(Protocol):
    """Executes a concrete resolved step against the target system."""
    kind: str

    def execute(self, step: ResolvedStep, ctx: RunContext) -> StepResult:
        """
        Execute step and return raw result.
        Must NOT raise exceptions on valid responses (including 4xx/5xx).
        Must populate transport_error on connection / DNS / timeout failures.
        """
        ...

@runtime_checkable
class Observer(Protocol):
    """Observes structural output of a StepResult and computes diffs."""
    def observe(self, result: StepResult) -> Observation:
        """Derive normalized structural observation from StepResult."""
        ...

    def compare(self, recorded: Observation, observed: Observation) -> ObservationDiff:
        """Classify each difference as identical, additive, or breaking."""
        ...

@runtime_checkable
class Fingerprinter(Protocol):
    """Computes pre-execution hashes and touched operation IDs."""
    def pre(self, step: ResolvedStep, ctx: RunContext) -> Fingerprint:
        """Compute pre-execution input hash (e.g. operation hash from spec)."""
        ...

    def touches(self, test: dict[str, Any], trace: dict[str, Any] | None) -> list[str]:
        """Return list of touched operation IDs for selection / impact analysis."""
        ...

@runtime_checkable
class AssertionType(Protocol):
    """Evaluates a typed expectation and statically declares read paths."""
    name: str

    def reads(self, spec: dict[str, Any]) -> list[str]:
        """
        Declare observation paths this expectation reads.
        Core uses this to determine if a breaking diff renders this expectation unevaluable.
        """
        ...

    def evaluate(self, spec: dict[str, Any], result: StepResult, ctx: RunContext) -> bool | str:
        """
        Evaluate expectation against result.
        Returns True if satisfied, False if violated, or 'missing' if an asserted key is absent.
        MUST NOT assign test outcome.
        """
        ...

@runtime_checkable
class Healer(Protocol):
    """Proposes deterministic repairs for healable trace fields."""
    def propose(self, step: ResolvedStep, diff: dict[str, Any], ctx: RunContext) -> dict[str, Any] | None:
        """
        Propose trace modifications for healable fields only.
        MUST NEVER modify expectations, data bindings, or test files.
        """
        ...

@runtime_checkable
class EvidenceCollector(Protocol):
    """Collects and masks execution artifacts for persistent storage."""
    def collect(self, result: StepResult, ctx: RunContext) -> list[Artifact]:
        """Return masked execution artifacts."""
        ...

@runtime_checkable
class SessionProvider(Protocol):
    """Optional lifecycle manager for shared state or connections."""
    def open(self, ctx: RunContext) -> Any:
        ...

    def close(self, session: Any) -> None:
        ...
