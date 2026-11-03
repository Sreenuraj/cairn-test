"""
API Plugin registration for cairn-test (T2.8).
"""

from __future__ import annotations
from typing import Any

from cairn_test.contracts import Fingerprint, Fingerprinter, ResolvedStep, RunContext
from cairn_test.core.plugins import PluginRegistry
from cairn_test.plugins.api.assertions import (
    HeaderAssertion,
    JsonPathAssertion,
    SchemaFromSpecAssertion,
    StateAssertion,
    StatusAssertion,
)
from cairn_test.plugins.api.evidence import ApiEvidenceCollector
from cairn_test.plugins.api.http import HttpStepExecutor
from cairn_test.plugins.api.observer import ApiObserver
from cairn_test.plugins.api.spec import OpenAPISpec

class ApiFingerprinter:
    def __init__(self, spec: OpenAPISpec | None = None):
        self.spec = spec

    def pre(self, step: ResolvedStep, ctx: RunContext) -> Fingerprint:
        if self.spec:
            try:
                op_def = self.spec.get_operation(step.operation)
                return Fingerprint(data={"op_hash": op_def.op_hash})
            except KeyError:
                pass
        return Fingerprint(data={"op_hash": f"op-{step.operation}"})

    def touches(self, test: dict[str, Any], trace: dict[str, Any] | None) -> list[str]:
        return [s.get("op", s["id"]) for s in test.get("steps", [])]

def register_api_plugin(
    registry: PluginRegistry,
    spec: OpenAPISpec | None = None,
    base_url: str = "",
) -> None:
    """Registers all components of the API plugin into the PluginRegistry."""
    http_exec = HttpStepExecutor(spec=spec, base_url=base_url)
    observer = ApiObserver()
    fingerprinter = ApiFingerprinter(spec=spec)
    evidence_collector = ApiEvidenceCollector()

    registry.register_step_executor("http", http_exec, version="0.1.0")
    registry.register_observer("http", observer)
    registry.register_fingerprinter("http", fingerprinter)
    registry.register_evidence_collector("http", evidence_collector)

    # Register assertions
    registry.register_assertion("status", StatusAssertion())
    registry.register_assertion("header", HeaderAssertion())
    registry.register_assertion("jsonpath", JsonPathAssertion())
    registry.register_assertion("schema", SchemaFromSpecAssertion(spec=spec))
    registry.register_assertion("state", StateAssertion(executor=http_exec))
