"""
CLI Step Plugin for cairn-test (T7.1, Acceptance 7).

Proves domain neutrality: a CLI-command step type using only the contracts,
with zero core engine changes.
"""

from __future__ import annotations
import subprocess
from typing import Any

from cairn_test.contracts import (
    Artifact,
    AssertionType,
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

class CliStepExecutor:
    """Executes local command-line steps."""

    def execute(self, step: ResolvedStep, ctx: RunContext) -> StepResult:
        cmd = step.params.get("command") or step.body or []
        if isinstance(cmd, str):
            cmd = cmd.split()

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return StepResult(
                step_id=step.id,
                status_code=res.returncode,
                headers={"stdout": res.stdout, "stderr": res.stderr},
                data={"stdout": res.stdout, "stderr": res.stderr, "exit_code": res.returncode},
            )
        except Exception as e:
            return StepResult(
                step_id=step.id,
                status_code=None,
                transport_error=str(e),
            )

class CliObserver:
    """Observes exit code and output structure."""

    def observe(self, result: StepResult) -> Observation:
        return Observation(
            status=result.status_code or 0,
            headers=["stdout", "stderr"],
            body_shape={"exit_code": "integer", "stdout": "string", "stderr": "string"},
        )

    def diff(self, recorded: Observation, observed: Observation) -> ObservationDiff:
        breaking = []
        if recorded.status != observed.status:
            breaking.append("$.status")
        return ObservationDiff(
            kind=DiffKind.BREAKING if breaking else DiffKind.IDENTICAL,
            breaking_paths=breaking,
        )

class CliFingerprinter:
    def fingerprint(self, step: ResolvedStep, ctx: RunContext) -> Fingerprint:
        return Fingerprint(data={"cmd": step.params.get("command")})

    def touches(self, test: dict[str, Any], trace: dict[str, Any] | None) -> list[str]:
        return [s.get("id", "step") for s in test.get("steps", [])]

class CliEvidenceCollector:
    def collect(self, result: StepResult, ctx: RunContext) -> list[Artifact]:
        stdout_txt = result.data.get("stdout", "") if isinstance(result.data, dict) else ""
        return [
            Artifact(
                name="stdout.log",
                media_type="text/plain",
                data=stdout_txt.encode("utf-8"),
            )
        ]

class ExitCodeAssertion:
    name = "exit_code"

    def reads(self, spec: dict[str, Any]) -> list[str]:
        return ["$.status"]

    def evaluate(self, spec: dict[str, Any], result: StepResult, ctx: RunContext) -> bool | str:
        expected = spec.get("exit_code", 0)
        return result.status_code == expected

class StdoutContainsAssertion:
    name = "stdout_contains"

    def reads(self, spec: dict[str, Any]) -> list[str]:
        return ["$.stdout"]

    def evaluate(self, spec: dict[str, Any], result: StepResult, ctx: RunContext) -> bool | str:
        expected = spec.get("stdout_contains", "")
        stdout = result.data.get("stdout", "") if isinstance(result.data, dict) else ""
        return expected in stdout

def register_cli_plugin(registry: PluginRegistry) -> None:
    """Registers CLI step plugin into the PluginRegistry."""
    registry.register_step_executor("cli", CliStepExecutor(), version="0.1.0")
    registry.register_observer("cli", CliObserver())
    registry.register_fingerprinter("cli", CliFingerprinter())
    registry.register_evidence_collector("cli", CliEvidenceCollector())
    registry.register_assertion("exit_code", ExitCodeAssertion())
    registry.register_assertion("stdout_contains", StdoutContainsAssertion())
