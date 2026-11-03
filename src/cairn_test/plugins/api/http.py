"""
HTTP step executor and auth helpers for cairn-test API plugin (T2.2, T2.3, FR-A2, FR-A6).

Uses Python standard library (urllib.request) for zero extra dependencies.
"""

from __future__ import annotations
import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from cairn_test.contracts import ResolvedStep, RunContext, StepResult
from cairn_test.plugins.api.jsonpath import extract_jsonpath
from cairn_test.plugins.api.spec import OpenAPISpec

def apply_auth_helper(auth_val: str | dict[str, str], headers: dict[str, str]) -> None:
    """FR-A6: Applies bearer, basic, or API key authentication."""
    if isinstance(auth_val, str):
        auth_str = auth_val.strip()
        if auth_str.lower().startswith("bearer ") or auth_str.lower().startswith("basic "):
            headers["authorization"] = auth_str
        elif ":" in auth_str:
            # username:password -> Basic auth
            encoded = base64.b64encode(auth_str.encode("utf-8")).decode("ascii")
            headers["authorization"] = f"Basic {encoded}"
        else:
            # Default token string -> Bearer auth
            headers["authorization"] = f"Bearer {auth_str}"
    elif isinstance(auth_val, dict):
        # Explicit auth format, e.g. {"header": "X-API-Key", "key": "secret"}
        if "header" in auth_val and "key" in auth_val:
            headers[auth_val["header"].lower()] = auth_val["key"]
        elif "basic" in auth_val:
            creds = auth_val["basic"]
            encoded = base64.b64encode(creds.encode("utf-8")).decode("ascii")
            headers["authorization"] = f"Basic {encoded}"
        elif "bearer" in auth_val:
            headers["authorization"] = f"Bearer {auth_val['bearer']}"

class HttpStepExecutor:
    """Executes HTTP steps against a target API using an OpenAPI spec."""
    kind = "http"

    def __init__(self, spec: OpenAPISpec | None = None, base_url: str = ""):
        self.spec = spec
        self.base_url = base_url.rstrip("/")

    def execute(self, step: ResolvedStep, ctx: RunContext) -> StepResult:
        # Determine method, path, and base URL
        method = step.method.upper()
        path = step.path
        base = self.base_url or ctx.variables.get("base_url", "")

        # Format path parameters (e.g. /orders/{id}) and query parameters
        url_path = path
        all_params: dict[str, Any] = {}
        if isinstance(step.params, dict):
            for k, v in step.params.items():
                if k == "params" and isinstance(v, dict):
                    all_params.update(v)
                else:
                    all_params[k] = v

        path_vars = set(re.findall(r"\{([^}]+)\}", url_path))
        query_params: dict[str, Any] = {}
        for p_name, p_val in all_params.items():
            if p_name in path_vars:
                url_path = url_path.replace(f"{{{p_name}}}", urllib.parse.quote(str(p_val), safe=""))
            elif p_name not in ("body", "headers") and not isinstance(p_val, dict):
                query_params[p_name] = p_val

        if query_params and method == "GET":
            delimiter = "&" if "?" in url_path else "?"
            url_path += delimiter + urllib.parse.urlencode(query_params, doseq=True)

        full_url = f"{base.rstrip('/')}{url_path}" if base else url_path

        # Prepare headers
        req_headers: dict[str, str] = {
            "accept": "application/json",
            "user-agent": "cairn-test/0.1.0",
        }
        for k, v in step.headers.items():
            req_headers[k.lower()] = str(v)

        # Apply authentication
        if step.auth:
            apply_auth_helper(step.auth, req_headers)

        # Prepare request body
        req_data: bytes | None = None
        if step.body is not None and method in ["POST", "PUT", "PATCH"]:
            req_headers["content-type"] = "application/json"
            if isinstance(step.body, (dict, list)):
                req_data = json.dumps(step.body).encode("utf-8")
            elif isinstance(step.body, str):
                req_data = step.body.encode("utf-8")
            elif isinstance(step.body, bytes):
                req_data = step.body

        # Construct urllib Request
        req = urllib.request.Request(
            url=full_url,
            data=req_data,
            headers=req_headers,
            method=method,
        )

        timeout_sec = max(0.5, step.timeout_ms / 1000.0)
        start_t = time.perf_counter()

        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                status_code = resp.status
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                raw_body = resp.read()
                data = self._parse_body(raw_body, resp_headers.get("content-type", ""))
                return StepResult(
                    step_id=step.id,
                    status_code=status_code,
                    headers=resp_headers,
                    data=data,
                    duration_ms=elapsed_ms,
                    transport_error=None,
                )
        except urllib.error.HTTPError as http_err:
            # HTTP 4xx / 5xx are valid step results, NOT transport errors!
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            resp_headers = {k.lower(): v for k, v in http_err.headers.items()}
            raw_body = http_err.read()
            data = self._parse_body(raw_body, resp_headers.get("content-type", ""))
            return StepResult(
                step_id=step.id,
                status_code=http_err.code,
                headers=resp_headers,
                data=data,
                duration_ms=elapsed_ms,
                transport_error=None,
            )
        except urllib.error.URLError as url_err:
            # Transport error (connection refused, DNS error, timeout)
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            return StepResult(
                step_id=step.id,
                status_code=None,
                headers={},
                data=None,
                duration_ms=elapsed_ms,
                transport_error=str(url_err.reason),
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            return StepResult(
                step_id=step.id,
                status_code=None,
                headers={},
                data=None,
                duration_ms=elapsed_ms,
                transport_error=str(exc),
            )

    def _parse_body(self, raw_body: bytes, content_type: str) -> Any:
        if not raw_body:
            return None
        if "application/json" in content_type.lower() or content_type == "":
            try:
                return json.loads(raw_body.decode("utf-8"))
            except Exception:
                pass
        try:
            return raw_body.decode("utf-8")
        except Exception:
            return raw_body

