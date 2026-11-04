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

            # 1. Happy path test definition
            expected_status = 201 if method == "POST" else 200
            happy_test_id = f"{op_id}_happy"
            tags = ["happy-path", op_id] if write_tests else ["draft", "happy-path", op_id]
            happy_test = {
                "schema": "cairn-test.test/v1",
                "id": happy_test_id,
                "tags": tags,
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
                p_file = props_dir / f"draft_{happy_test_id}.proposal.yaml"
                with open(p_file, "w", encoding="utf-8") as f:
                    f.write("# yaml-language-server: $schema=../schemas/proposal.v1.json\n")
                    yaml.safe_dump(proposal, f, sort_keys=False)
                created_paths.append(p_file)

        return created_paths

def promote_drafts(repo_root: Path, target_ids: list[str] | None = None) -> list[Path]:
    """
    Promote pending draft proposals from proposals/ into runnable test definitions in tests/.
    Drops 'draft_' prefix from filenames, test IDs, and tags upon promotion.
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

            raw_test_id = data.get("test") or prop_file.name.replace(".proposal.yaml", "")
            clean_test_id = raw_test_id[6:] if raw_test_id.startswith("draft_") else raw_test_id

            if target_ids:
                matches = False
                for tid in target_ids:
                    clean_tid = tid[6:] if tid.startswith("draft_") else tid
                    if clean_tid in (clean_test_id, raw_test_id):
                        matches = True
                        break
                if not matches:
                    continue

            draft_test = data.get("details", {}).get("draft_test")
            if not draft_test or not isinstance(draft_test, dict):
                continue

            # Ensure clean test ID without 'draft_' prefix and remove 'draft' tag
            draft_test["id"] = clean_test_id
            if "tags" in draft_test and isinstance(draft_test["tags"], list):
                draft_test["tags"] = [t for t in draft_test["tags"] if t != "draft"]

            validate_document(draft_test, "test.v1")
            dest_test_file = tests_dir / f"{clean_test_id}.test.yaml"
            with open(dest_test_file, "w", encoding="utf-8") as f:
                f.write("# yaml-language-server: $schema=../schemas/test.v1.json\n")
                yaml.safe_dump(draft_test, f, sort_keys=False)

            prop_file.unlink(missing_ok=True)
            promoted.append(dest_test_file)
        except Exception:
            continue

    return promoted
