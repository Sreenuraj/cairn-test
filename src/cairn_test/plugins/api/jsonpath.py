"""
Lightweight JSONPath extractor for cairn-test API plugin (FR-A2).
Supports $, $.field, $.field.sub, and array indices $[0].
"""

from __future__ import annotations
import re
from typing import Any

PATH_SPLIT = re.compile(r"\.|\[(\d+)\]")

def extract_jsonpath(data: Any, path: str) -> Any:
    """Extracts a value from nested dicts/lists using a dot/bracket JSONPath."""
    if data is None:
        return None
    p = path.strip()
    if p == "$" or p == "":
        return data

    if p.startswith("$."):
        p = p[2:]
    elif p.startswith("$"):
        p = p[1:]

    tokens = [t for t in re.split(r"\.|\[|\]", p) if t]
    curr = data
    for token in tokens:
        if isinstance(curr, dict):
            if token in curr:
                curr = curr[token]
            else:
                return None
        elif isinstance(curr, list):
            try:
                idx = int(token)
                if 0 <= idx < len(curr):
                    curr = curr[idx]
                else:
                    return None
            except ValueError:
                # Field access on array elements (e.g. $[*].field)
                return [item.get(token) for item in curr if isinstance(item, dict) and token in item]
        else:
            return None
    return curr

