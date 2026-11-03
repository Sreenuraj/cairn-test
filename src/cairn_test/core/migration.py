"""
Schema migration framework for cairn-test (T5.4, FR-M1).

Enables upgrading stored test, trace, and approval YAML files across schema versions.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import yaml

@dataclass
class MigrationResult:
    path: Path
    kind: str
    old_version: str
    new_version: str
    modified: bool
    changes: list[str]

# Registry of (kind, from_version) -> (to_version, migrator_function)
MIGRATION_REGISTRY: dict[tuple[str, str], tuple[str, Callable[[dict[str, Any]], tuple[dict[str, Any], list[str]]]]] = {}

def register_migration(
    kind: str,
    from_version: str,
    to_version: str,
    migrator: Callable[[dict[str, Any]], tuple[dict[str, Any], list[str]]],
) -> None:
    MIGRATION_REGISTRY[(kind, from_version)] = (to_version, migrator)

# Register dummy/example migration: cairn-test.test/v0 -> cairn-test.test/v1
def _migrate_test_v0_to_v1(doc: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    changes = []
    updated = dict(doc)
    updated["schema"] = "cairn-test.test/v1"
    changes.append("Updated schema identifier to cairn-test.test/v1")
    # Legacy 'timeout' renamed to 'timeout_ms'
    for step in updated.get("steps", []):
        if "timeout" in step and "timeout_ms" not in step:
            step["timeout_ms"] = int(step.pop("timeout") * 1000)
            changes.append(f"Converted step '{step.get('id')}' timeout from seconds to timeout_ms")
    return updated, changes

register_migration("cairn-test.test", "cairn-test.test/v0", "cairn-test.test/v1", _migrate_test_v0_to_v1)

class MigrationEngine:
    """Discovers and migrates stored files across schema versions."""

    def migrate_file(self, file_path: Path, dry_run: bool = False) -> MigrationResult | None:
        if not file_path.is_file():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                data = yaml.safe_load(f)
            except Exception:
                return None

        if not isinstance(data, dict) or "schema" not in data:
            return None

        current_schema = str(data["schema"])
        kind = current_schema.split("/")[0]

        key = (kind, current_schema)
        if key not in MIGRATION_REGISTRY:
            return None

        to_version, migrator = MIGRATION_REGISTRY[key]
        updated_data, changes = migrator(data)

        if not dry_run and changes:
            with open(file_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(updated_data, f, sort_keys=False)

        return MigrationResult(
            path=file_path,
            kind=kind,
            old_version=current_schema,
            new_version=to_version,
            modified=len(changes) > 0,
            changes=changes,
        )

    def migrate_directory(self, base_dir: Path, dry_run: bool = False) -> list[MigrationResult]:
        results: list[MigrationResult] = []
        for p in base_dir.rglob("*.yaml"):
            res = self.migrate_file(p, dry_run=dry_run)
            if res and res.modified:
                results.append(res)
        return results
