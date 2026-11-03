"""
Evidence collector with secret and PII masking (T2.6, FR-C8, NFR-5).

Guarantees that sensitive headers, field names, and regex patterns (passwords, tokens, SSNs)
are redacted before writing evidence or traces to disk.
"""

from __future__ import annotations
import json
import re
from typing import Any

from cairn_test.config import DEFAULT_MASKING_NAMES, DEFAULT_MASKING_PATTERNS
from cairn_test.contracts import Artifact, RunContext, StepResult

class EvidenceMasker:
    """Masks secret keys and sensitive patterns from dictionaries, strings, and headers."""

    def __init__(self, names: list[str] | None = None, patterns: list[str] | None = None):
        self.names = set(n.lower() for n in (names or DEFAULT_MASKING_NAMES))
        self.compiled_patterns = [
            re.compile(p, re.IGNORECASE) for p in (patterns or DEFAULT_MASKING_PATTERNS)
        ]

    def mask(self, data: Any) -> Any:
        if isinstance(data, dict):
            masked_dict = {}
            for k, v in data.items():
                k_norm = str(k).lower().replace("-", "_")
                if any(k_norm == name or name in k_norm or name.replace("_", "") in k_norm.replace("_", "") for name in self.names):
                    masked_dict[k] = "[REDACTED]"
                else:
                    masked_dict[k] = self.mask(v)
            return masked_dict
        elif isinstance(data, list):
            return [self.mask(item) for item in data]
        elif isinstance(data, str):
            res = data
            for pat in self.compiled_patterns:
                res = pat.sub("[REDACTED]", res)
            return res
        return data

class ApiEvidenceCollector:
    """Collects masked HTTP execution evidence (raw responses, timings, headers)."""

    def __init__(self, names: list[str] | None = None, patterns: list[str] | None = None):
        self.masker = EvidenceMasker(names=names, patterns=patterns)

    def collect(self, result: StepResult, ctx: RunContext) -> list[Artifact]:
        artifacts: list[Artifact] = []

        # Mask headers and response data
        masked_headers = self.masker.mask(result.headers)
        masked_data = self.masker.mask(result.data)

        # 1. Response body artifact
        if masked_data is not None:
            content_str = (
                json.dumps(masked_data, indent=2)
                if isinstance(masked_data, (dict, list))
                else str(masked_data)
            )
            artifacts.append(
                Artifact(
                    name="response.json",
                    media_type="application/json",
                    content=content_str,
                    masked=True,
                )
            )

        # 2. Execution metadata artifact
        meta = {
            "step_id": result.step_id,
            "status_code": result.status_code,
            "duration_ms": result.duration_ms,
            "transport_error": result.transport_error,
            "headers": masked_headers,
        }
        artifacts.append(
            Artifact(
                name="meta.json",
                media_type="application/json",
                content=json.dumps(meta, indent=2),
                masked=True,
            )
        )

        return artifacts
