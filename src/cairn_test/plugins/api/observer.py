"""
API Observer and response diff engine (T2.5, FR-A4, FR-A5, FR-C15).

Implements exact response diff rules from plan.md section 14:
- Field added -> additive
- Header added -> additive
- Key order or array length changed -> identical
- Field removed -> breaking
- Field type changed -> breaking
- Field observed as null where never null -> breaking
- Header removed -> breaking
- Status code changed -> breaking
"""

from __future__ import annotations
from typing import Any
from cairn_test.contracts import (
    DiffChange,
    DiffKind,
    Observation,
    ObservationDiff,
    StepResult,
)

def normalize_body_shape(data: Any) -> Any:
    """Derives normalized structural shape (keys and data types, ignoring literals and array lengths)."""
    if data is None:
        return "null"
    if isinstance(data, bool):
        return "boolean"
    if isinstance(data, int):
        return "integer"
    if isinstance(data, float):
        return "number"
    if isinstance(data, str):
        return "string"
    if isinstance(data, dict):
        return {k: normalize_body_shape(v) for k, v in data.items()}
    if isinstance(data, list):
        if not data:
            return []
        # Merge shapes of array elements
        merged: dict[str, Any] = {}
        has_dict = False
        non_dict_types = set()
        for item in data:
            if isinstance(item, dict):
                has_dict = True
                norm_item = normalize_body_shape(item)
                if isinstance(norm_item, dict):
                    merged.update(norm_item)
            else:
                non_dict_types.add(normalize_body_shape(item))
        if has_dict:
            return [merged]
        if non_dict_types:
            return [sorted(list(non_dict_types))[0]]
        return []
    return type(data).__name__

class ApiObserver:
    """Observes HTTP step results and computes structured observation diffs."""

    def observe(self, result: StepResult) -> Observation:
        # Ignore volatile headers like date
        ignored_headers = {"date", "content-length", "server"}
        headers = sorted([k.lower() for k in result.headers.keys() if k.lower() not in ignored_headers])
        body_shape = normalize_body_shape(result.data)
        return Observation(
            status=result.status_code or 0,
            headers=headers,
            body_shape=body_shape,
        )

    def compare(self, recorded: Observation, observed: Observation) -> ObservationDiff:
        changes: list[DiffChange] = []

        # 1. Status code diff
        if recorded.status != observed.status:
            changes.append(
                DiffChange(
                    path="$.status",
                    kind=DiffKind.BREAKING,
                    recorded=recorded.status,
                    observed=observed.status,
                    detail=f"Status code changed from {recorded.status} to {observed.status}",
                )
            )

        # 2. Header diffs
        rec_headers = set(h.lower() for h in recorded.headers)
        obs_headers = set(h.lower() for h in observed.headers)

        for h in sorted(rec_headers - obs_headers):
            changes.append(
                DiffChange(
                    path=f"headers.{h}",
                    kind=DiffKind.BREAKING,
                    recorded=h,
                    observed=None,
                    detail=f"Header '{h}' removed",
                )
            )

        for h in sorted(obs_headers - rec_headers):
            changes.append(
                DiffChange(
                    path=f"headers.{h}",
                    kind=DiffKind.ADDITIVE,
                    recorded=None,
                    observed=h,
                    detail=f"Header '{h}' added",
                )
            )

        # 3. Body shape diffs
        self._diff_shapes(recorded.body_shape, observed.body_shape, prefix="$", changes=changes)

        return ObservationDiff(changes=changes)

    def _diff_shapes(self, rec: Any, obs: Any, prefix: str, changes: list[DiffChange]) -> None:
        # Null check
        if rec != "null" and obs == "null":
            changes.append(
                DiffChange(
                    path=prefix,
                    kind=DiffKind.BREAKING,
                    recorded=rec,
                    observed="null",
                    detail=f"Field '{prefix}' observed as null",
                )
            )
            return

        if isinstance(rec, dict) and isinstance(obs, dict):
            # Check removed keys -> breaking
            for k in sorted(rec.keys()):
                field_path = f"{prefix}.{k}"
                if k not in obs:
                    changes.append(
                        DiffChange(
                            path=field_path,
                            kind=DiffKind.BREAKING,
                            recorded=rec[k],
                            observed=None,
                            detail=f"Field '{k}' removed",
                        )
                    )
                else:
                    self._diff_shapes(rec[k], obs[k], prefix=field_path, changes=changes)

            # Check added keys -> additive
            for k in sorted(obs.keys()):
                field_path = f"{prefix}.{k}"
                if k not in rec:
                    changes.append(
                        DiffChange(
                            path=field_path,
                            kind=DiffKind.ADDITIVE,
                            recorded=None,
                            observed=obs[k],
                            detail=f"Field '{k}' added",
                        )
                    )
        elif isinstance(rec, list) and isinstance(obs, list):
            # Key order / array length differences are identical
            if rec and obs:
                self._diff_shapes(rec[0], obs[0], prefix=f"{prefix}[*]", changes=changes)
            elif not rec and obs:
                changes.append(
                    DiffChange(
                        path=prefix,
                        kind=DiffKind.ADDITIVE,
                        recorded=[],
                        observed=obs,
                        detail="Array elements observed",
                    )
                )
            elif rec and not obs:
                # Still identical or empty array
                pass
        else:
            # Primitive type comparison
            if rec != obs:
                # E.g. "number" != "string", or dict != list
                changes.append(
                    DiffChange(
                        path=prefix,
                        kind=DiffKind.BREAKING,
                        recorded=rec,
                        observed=obs,
                        detail=f"Type changed from {rec} to {obs}",
                    )
                )

