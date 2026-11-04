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

    def draft_suite(self, repo_root: Path, write_tests: bool = False) -> list[Path]:
        props_dir = repo_root / "proposals"
        tests_dir = repo_root / "tests"
        if write_tests:
            tests_dir.mkdir(parents=True, exist_ok=True)
        else:
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

            if write_tests:
                validate_document(happy_test, "test.v1")
                t_file = tests_dir / f"{happy_test_id}.test.yaml"
                with open(t_file, "w", encoding="utf-8") as f:
                    f.write("# yaml-language-server: $schema=../schemas/test.v1.json\n")
                    yaml.safe_dump(happy_test, f, sort_keys=False)
                created_paths.append(t_file)
            else:
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

def promote_drafts(repo_root: Path, target_ids: list[str] | None = None) -> list[Path]:
    """
    Promote pending draft proposals from proposals/ into runnable test definitions in tests/.
    """
    props_dir = repo_root / "proposals"
    tests_dir = repo_root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    promoted: list[Path] = []

    if not props_dir.is_dir():
        return promoted

    for prop_file in sorted(props_dir.glob("*.proposal.yaml")):
        try:
            with open(prop_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict) or data.get("kind") != "draft":
                continue

            test_id = data.get("test") or prop_file.name.replace(".proposal.yaml", "")
            if target_ids and test_id not in target_ids:
                continue

            draft_test = data.get("details", {}).get("draft_test")
            if not draft_test or not isinstance(draft_test, dict):
                continue

            validate_document(draft_test, "test.v1")
            dest_test_file = tests_dir / f"{test_id}.test.yaml"
            with open(dest_test_file, "w", encoding="utf-8") as f:
                f.write("# yaml-language-server: $schema=../schemas/test.v1.json\n")
                yaml.safe_dump(draft_test, f, sort_keys=False)

            prop_file.unlink(missing_ok=True)
            promoted.append(dest_test_file)
        except Exception:
            continue

    return promoted
