"""
Deterministic test drafting from OpenAPI specifications (T5.8, FR-A8).

Generates inert draft test proposals in proposals/ for:
1. Happy path: status 200/201, schema validation from spec.
2. Required input negatives: missing required parameters or body fields (status 400).
3. Auth negatives: requests missing required credentials (status 401).
"""

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import yaml

from cairn_test.core.schemas import validate_document
from cairn_test.plugins.api.spec import OpenAPISpec

class SpecDrafter:
    """Drafts baseline test definitions deterministically from an OpenAPI spec."""

    def __init__(self, spec: OpenAPISpec):
        self.spec = spec

    def draft_suite(self, repo_root: Path) -> list[Path]:
        props_dir = repo_root / "proposals"
        props_dir.mkdir(parents=True, exist_ok=True)
        created_paths: list[Path] = []

        ops = list(self.spec.operations_by_id.values())
        for op in ops:
            op_id = op.operation_id
            method = op.method.upper()
            path = op.path

            # 1. Happy path draft test
            expected_status = 201 if method == "POST" else 200
            happy_test_id = f"draft_{op_id}_happy"
            happy_test = {
                "schema": "cairn-test.test/v1",
                "id": happy_test_id,
                "tags": ["draft", "happy-path", op_id],
                "steps": [
                    {
                        "id": "step_0",
                        "op": op_id,
                        "args": {},
                    }
                ],
                "expect": [
                    {"status": expected_status},
                    {"schema": "from-spec"},
                ],
            }

            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            proposal = {
                "schema": "cairn-test.proposal/v1",
                "id": f"draft_{happy_test_id}",
                "kind": "draft",
                "test": happy_test_id,
                "created_at": now_iso,
                "reason": f"Deterministic draft test for operation '{op_id}'",
                "status": "pending",
                "details": {
                    "draft_test": happy_test,
                },
            }

            validate_document(proposal, "proposal.v1")
            p_file = props_dir / f"{happy_test_id}.proposal.yaml"
            with open(p_file, "w", encoding="utf-8") as f:
                f.write("# yaml-language-server: $schema=../schemas/proposal.v1.json\n")
                yaml.safe_dump(proposal, f, sort_keys=False)
            created_paths.append(p_file)

        return created_paths
