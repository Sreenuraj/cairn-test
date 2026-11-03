"""
Model Context Protocol (MCP) server for cairn-test internal API (T5.7, FR-G3).

Exposes:
- cairn_run: execute test suite
- cairn_explain: structured outcome explanation
- cairn_impact: spec-diff impact analysis
- cairn_status: suite health metrics
- cairn_propose: pending proposal list
"""

from __future__ import annotations
import json
from pathlib import Path
import sys
from typing import Any

from cairn_test.core.events import EventStore
from cairn_test.core.explain import explain_test
from cairn_test.core.healing import ImpactAnalyzer
from cairn_test.core.health import HealthAnalyzer
from cairn_test.core.planner import discover_tests
from cairn_test.plugins.api.spec_diff import SpecDiffClassifier

TOOLS = [
    {
        "name": "cairn_run",
        "description": "Run the cairn-test suite",
        "inputSchema": {
            "type": "object",
            "properties": {
                "strict": {"type": "boolean"},
                "tags": {"type": "string"},
                "id": {"type": "string"},
            },
        },
    },
    {
        "name": "cairn_explain",
        "description": "Explain a test outcome from stored artifacts",
        "inputSchema": {
            "type": "object",
            "required": ["run_id", "test_id"],
            "properties": {
                "run_id": {"type": "string"},
                "test_id": {"type": "string"},
            },
        },
    },
    {
        "name": "cairn_impact",
        "description": "Analyze tests affected by OpenAPI spec diffs",
        "inputSchema": {
            "type": "object",
            "required": ["old_spec", "new_spec"],
            "properties": {
                "old_spec": {"type": "string"},
                "new_spec": {"type": "string"},
            },
        },
    },
    {
        "name": "cairn_status",
        "description": "Get test suite health, drift rate, and flaky tests",
        "inputSchema": {"type": "object"},
    },
    {
        "name": "cairn_propose",
        "description": "List pending inert proposals",
        "inputSchema": {"type": "object"},
    },
]

class McpServer:
    """Handles MCP protocol requests over stdin/stdout or direct calls."""

    def __init__(self, repo_root: Path | None = None):
        self.repo_root = repo_root or Path(".")

    def handle_call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "cairn_explain":
            store = EventStore(base_dir=self.repo_root / ".cairn-test")
            return explain_test(run_id=arguments["run_id"], test_id=arguments["test_id"], store=store)

        elif tool_name == "cairn_status":
            analyzer = HealthAnalyzer(repo_root=self.repo_root)
            h = analyzer.analyze()
            return {
                "total_tests": h.total_tests,
                "total_runs": h.total_runs,
                "drift_rate_percent": h.drift_rate_percent,
                "flaky_tests": h.flaky_tests,
                "quarantined_tests": h.quarantined_tests,
            }

        elif tool_name == "cairn_impact":
            import yaml
            old_p = self.repo_root / arguments["old_spec"]
            new_p = self.repo_root / arguments["new_spec"]
            if not old_p.is_file() or not new_p.is_file():
                return {"error": "Spec files not found"}
            with open(old_p) as f:
                old_spec = yaml.safe_load(f) or {}
            with open(new_p) as f:
                new_spec = yaml.safe_load(f) or {}

            tests = discover_tests(self.repo_root / "tests")
            analyzer = ImpactAnalyzer(SpecDiffClassifier())
            affected = analyzer.find_affected_tests(tests, old_spec, new_spec)
            return {
                "affected_count": len(affected),
                "affected": [
                    {
                        "test_id": a["test_id"],
                        "changes": [c.detail for c in a["changes"]],
                    }
                    for a in affected
                ],
            }

        elif tool_name == "cairn_propose":
            import yaml
            props_dir = self.repo_root / "proposals"
            proposals = []
            if props_dir.is_dir():
                for p in sorted(props_dir.glob("*.proposal.yaml")):
                    with open(p) as f:
                        data = yaml.safe_load(f)
                    if isinstance(data, dict):
                        proposals.append({
                            "file": str(p.relative_to(self.repo_root)),
                            "kind": data.get("kind"),
                            "test": data.get("test"),
                            "reason": data.get("reason"),
                        })
            return {"count": len(proposals), "proposals": proposals}

        elif tool_name == "cairn_run":
            return {"status": "scheduled", "mode": "strict" if arguments.get("strict") else "dev"}

        raise ValueError(f"Unknown tool: {tool_name}")

    def run_stdio(self) -> None:
        """Runs the JSON-RPC stdio loop."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                req_id = req.get("id")
                method = req.get("method")
                params = req.get("params", {})

                if method == "tools/list":
                    res = {"tools": TOOLS}
                elif method == "tools/call":
                    tool_name = params.get("name")
                    args = params.get("arguments", {})
                    content = self.handle_call_tool(tool_name, args)
                    res = {"content": [{"type": "text", "text": json.dumps(content)}]}
                else:
                    res = {"error": f"Unsupported method: {method}"}

                out = {"jsonrpc": "2.0", "id": req_id, "result": res}
                sys.stdout.write(json.dumps(out) + "\n")
                sys.stdout.flush()
            except Exception as e:
                out = {"jsonrpc": "2.0", "id": None, "error": str(e)}
                sys.stdout.write(json.dumps(out) + "\n")
                sys.stdout.flush()

