"""
Newman / Postman collection generator and test runner (T6.5, FR-B2, FR-B3).
Generates a Postman v2.1.0 collection for all 30 behaviors with JavaScript test assertions.
"""

from __future__ import annotations
import json
from pathlib import Path
import re
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TESTS_DIR = REPO_ROOT / "bench" / "tests"
NEWMAN_DIR = REPO_ROOT / "bench" / "newman"
COLLECTION_FILE = NEWMAN_DIR / "collection.json"

def resolve_step_request(
    step: dict[str, Any],
    all_expect: list[dict[str, Any]],
    env: dict[str, Any],
) -> dict[str, Any]:
    step_id = step.get("id", "")
    op = step.get("op", "")
    args = step.get("args", {})
    body = args.get("body")
    headers = dict(args.get("headers", {}))
    params = dict(args.get("params", {}))

    # Also check top-level args for params like id
    for k, v in args.items():
        if k not in ("body", "headers", "params"):
            params[k] = v

    method = "GET"
    path = f"/{op}"

    op_lower = op.lower()
    if "login" in op_lower:
        method = "POST"
        path = "/auth/login"
    elif "refresh" in op_lower:
        method = "POST"
        path = "/auth/refresh"
    elif "logout" in op_lower:
        method = "POST"
        path = "/auth/logout"
    elif "createorder" in op_lower:
        method = "POST"
        path = "/orders"
    elif "createrefund" in op_lower or "refund" in op_lower:
        method = "POST"
        path = "/refunds"
    elif "updateshipping" in op_lower:
        method = "PUT"
        oid = params.get("id", "ord-seed-1")
        path = f"/orders/{oid}/shipping"
    elif "payorder" in op_lower:
        method = "POST"
        oid = params.get("id", "ord-seed-1")
        path = f"/orders/{oid}/pay"
    elif "cancelorder" in op_lower:
        method = "POST"
        oid = params.get("id", "ord-seed-1")
        path = f"/orders/{oid}/cancel"
    elif "getinventory" in op_lower:
        method = "GET"
        pid = params.get("id", "prod-1")
        path = f"/products/{pid}/inventory"
    elif "getproduct" in op_lower and "id" in params:
        method = "GET"
        path = f"/products/{params['id']}"
    elif "getproducts" in op_lower:
        method = "GET"
        query_str = urllib.parse.urlencode(params) if params else ""
        path = f"/products?{query_str}" if query_str else "/products"
    elif "getcustomer" in op_lower:
        method = "GET"
        path = "/customers/me"
    elif "updatecustomer" in op_lower:
        method = "PATCH"
        path = "/customers/me"
    elif "gethealth" in op_lower:
        method = "GET"
        path = "/health"
    elif "getopenapi" in op_lower:
        method = "GET"
        path = "/openapi.json"
    elif "getorders" in op_lower:
        method = "GET"
        path = "/orders"
    elif "getorder" in op_lower:
        method = "GET"
        oid = params.get("id", "ord-seed-1")
        path = f"/orders/{oid}"

    # Variable substitution
    for k, v in env.items():
        placeholder = f"{{{k}}}"
        path = path.replace(placeholder, str(v))
        if isinstance(body, dict):
            body_str = json.dumps(body).replace(placeholder, str(v))
            body = json.loads(body_str)

    auth_val = step.get("auth")
    if auth_val:
        for k, v in env.items():
            auth_val = auth_val.replace(f"{{{k}}}", str(v))
        headers["Authorization"] = f"Bearer {auth_val}"

    # Generate PM test script for expectations matching this step
    pm_tests = []
    step_expects = [e for e in all_expect if e.get("after") == step_id]
    for exp in step_expects:
        if "status" in exp:
            st = exp["status"]
            pm_tests.append(f"pm.test('Status code is {st}', function () {{ pm.response.to.have.status({st}); }});")
        if "jsonpath" in exp:
            jp = exp["jsonpath"]
            prop = jp.lstrip("$.")
            if "equals" in exp:
                eq = json.dumps(exp["equals"])
                pm_tests.append(f"pm.test('Field {prop} equals {eq}', function () {{ var json = pm.response.json(); pm.expect(json.{prop}).to.eql({eq}); }});")
            elif "exists" in exp:
                pm_tests.append(f"pm.test('Field {prop} exists', function () {{ var json = pm.response.json(); pm.expect(json.{prop}).to.not.be.undefined; }});")

    # Extractions
    extract_map = step.get("extract", {})

    header_list = [{"key": k, "value": v} for k, v in headers.items()]
    header_list.append({"key": "Content-Type", "value": "application/json"})

    req_obj: dict[str, Any] = {
        "name": step_id,
        "event": [
            {
                "listen": "test",
                "script": {
                    "type": "text/javascript",
                    "exec": pm_tests,
                },
            }
        ],
        "request": {
            "method": method,
            "header": header_list,
            "url": {
                "raw": f"{{{{base_url}}}}{path}",
                "host": ["{{base_url}}"],
                "path": [p for p in path.split("/") if p],
            },
        },
        "_extract": extract_map,
    }
    if body is not None:
        req_obj["request"]["body"] = {
            "mode": "raw",
            "raw": json.dumps(body),
            "options": {"raw": {"language": "json"}},
        }

    return req_obj

def generate_newman_collection() -> dict[str, Any]:
    NEWMAN_DIR.mkdir(parents=True, exist_ok=True)
    items = []

    for test_file in sorted(TESTS_DIR.glob("*.test.yaml")):
        with open(test_file, "r", encoding="utf-8") as f:
            t = yaml.safe_load(f)

        tid = t["id"]
        steps = t.get("steps", [])
        expect = t.get("expect", [])

        if len(steps) == 1:
            req_obj = resolve_step_request(steps[0], expect, {})
            req_obj["name"] = tid
            items.append(req_obj)
        else:
            # Multi-step test represented as a folder item
            child_items = []
            dummy_env: dict[str, Any] = {}
            for step in steps:
                child = resolve_step_request(step, expect, dummy_env)
                child_items.append(child)
            items.append({
                "name": tid,
                "item": child_items,
            })

    collection = {
        "info": {
            "_postman_id": "cairn-benchmark-suite",
            "name": "Reference Store API 30-Behavior Suite",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": items,
    }

    with open(COLLECTION_FILE, "w", encoding="utf-8") as f:
        json.dump(collection, f, indent=2)

    return collection

class NewmanRunner:
    """Executes collection requests against base_url and reports pass/fail."""

    def __init__(self, collection: dict[str, Any], base_url: str):
        self.collection = collection
        self.base_url = base_url.rstrip("/")

    def _execute_request(
        self,
        item: dict[str, Any],
        env: dict[str, Any],
        seeded_header: str | None = None,
    ) -> tuple[bool, int | None, dict[str, Any], str | None]:
        req = item["request"]
        method = req["method"]
        raw_url = req["url"]["raw"].replace("{{base_url}}", self.base_url)

        # Substitute env variables in URL
        for k, v in env.items():
            raw_url = raw_url.replace(f"{{{k}}}", str(v))

        headers = {h["key"]: h["value"] for h in req.get("header", [])}
        for k, v in env.items():
            for hk, hv in list(headers.items()):
                if f"{{{k}}}" in hv:
                    headers[hk] = hv.replace(f"{{{k}}}", str(v))

        if seeded_header:
            headers["X-Seeded-Change"] = seeded_header

        data = None
        if "body" in req and "raw" in req["body"]:
            raw_body = req["body"]["raw"]
            for k, v in env.items():
                raw_body = raw_body.replace(f"{{{k}}}", str(v))
            data = raw_body.encode("utf-8")

        url_req = urllib.request.Request(raw_url, data=data, headers=headers, method=method)
        passed = True
        error_msg = None
        status_code = None
        resp_json = {}

        try:
            with urllib.request.urlopen(url_req, timeout=5) as resp:
                status_code = resp.status
                body_bytes = resp.read()
                resp_json = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except urllib.error.HTTPError as he:
            status_code = he.code
            body_bytes = he.read()
            resp_json = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception as e:
            passed = False
            error_msg = str(e)

        # Execute assertions
        scripts = item.get("event", [{}])[0].get("script", {}).get("exec", [])
        for script_line in scripts:
            # Status check
            m_status = re.search(r"status\((\d+)\)", script_line)
            if m_status:
                expected_status = int(m_status.group(1))
                if status_code != expected_status:
                    passed = False
                    error_msg = f"Expected status {expected_status}, got {status_code}"

            # Equality check
            m_eq = re.search(r"pm\.expect\(json\.([\w.]+)\)\.to\.eql\((.*?)\);", script_line)
            if m_eq:
                prop_path = m_eq.group(1).split(".")
                cur = resp_json
                for part in prop_path:
                    if isinstance(cur, dict):
                        cur = cur.get(part)
                    else:
                        cur = None
                        break
                val = json.loads(m_eq.group(2))
                if cur != val:
                    passed = False
                    error_msg = f"Expected {m_eq.group(1)} to equal {val}, got {cur}"

            # Exists check
            m_exists = re.search(r"pm\.expect\(json\.([\w.]+)\)\.to\.not\.be\.undefined", script_line)
            if m_exists:
                prop_path = m_exists.group(1).split(".")
                cur = resp_json
                for part in prop_path:
                    if isinstance(cur, dict):
                        cur = cur.get(part)
                    else:
                        cur = None
                        break
                if cur is None:
                    passed = False
                    error_msg = f"Expected {m_exists.group(1)} to exist, got None"

        # Apply extractions into env
        extract_map = item.get("_extract", {})
        for var_name, jp in extract_map.items():
            prop = jp.lstrip("$.")
            val = resp_json.get(prop)
            if val is not None:
                env[var_name] = val

        return passed, status_code, resp_json, error_msg

    def run_all(self, seeded_header: str | None = None) -> dict[str, Any]:
        results = []
        for item in self.collection.get("item", []):
            name = item["name"]
            env: dict[str, Any] = {}

            if "item" in item:
                # Multi-step workflow
                test_passed = True
                last_status = None
                error_msg = None
                for step_item in item["item"]:
                    step_passed, step_status, _, step_err = self._execute_request(
                        step_item, env, seeded_header
                    )
                    last_status = step_status
                    if not step_passed:
                        test_passed = False
                        error_msg = f"Step '{step_item['name']}' failed: {step_err}"
                        break
                results.append({
                    "name": name,
                    "passed": test_passed,
                    "status_code": last_status,
                    "error": error_msg,
                })
            else:
                passed, status_code, _, error_msg = self._execute_request(
                    item, env, seeded_header
                )
                results.append({
                    "name": name,
                    "passed": passed,
                    "status_code": status_code,
                    "error": error_msg,
                })

        passed_count = sum(1 for r in results if r["passed"])
        failed_count = sum(1 for r in results if not r["passed"])
        return {
            "total": len(results),
            "passed": passed_count,
            "failed": failed_count,
            "results": results,
        }

if __name__ == "__main__":
    generate_newman_collection()
    print(f"Generated Newman collection in {COLLECTION_FILE}")
