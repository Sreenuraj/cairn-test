"""
Tests for HTTP step executor, auth helpers, and JSONPath extraction (T2.2, T2.3, FR-A2, FR-A6).
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading
from typing import Any
from cairn_test.contracts import ResolvedStep, RunContext
from cairn_test.plugins.api.http import HttpStepExecutor, apply_auth_helper
from cairn_test.plugins.api.jsonpath import extract_jsonpath

class MockServerHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass  # quiet test output

    def do_GET(self) -> None:
        if self.path == "/orders/123":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("ETag", "v1")
            self.end_headers()
            self.wfile.write(json.dumps({"id": "123", "total": 49.98, "status": "PLACED"}).encode("utf-8"))
        elif self.path == "/auth-check":
            auth = self.headers.get("Authorization", "")
            if auth == "Bearer secret-token":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"authenticated": true}')
            else:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "Unauthorized"}')
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "Not Found"}')

    def do_POST(self) -> None:
        if self.path == "/orders":
            content_len = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_len)
            payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            if not payload.get("items"):
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "Empty items"}')
                return
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"id": "ord-999", "total": 49.98}).encode("utf-8"))

def test_jsonpath_extraction():
    data = {
        "user": {"name": "Alice", "tokens": ["tok1", "tok2"]},
        "orders": [{"id": 1, "sku": "A"}, {"id": 2, "sku": "B"}],
        "total": 99.5
    }
    assert extract_jsonpath(data, "$.total") == 99.5
    assert extract_jsonpath(data, "$.user.name") == "Alice"
    assert extract_jsonpath(data, "$.user.tokens[0]") == "tok1"
    assert extract_jsonpath(data, "$.orders[1].sku") == "B"
    assert extract_jsonpath(data, "$.nonexistent") is None

def test_auth_helpers():
    headers = {}
    apply_auth_helper("my-jwt-token", headers)
    assert headers["authorization"] == "Bearer my-jwt-token"

    headers2 = {}
    apply_auth_helper("admin:secret", headers2)
    assert headers2["authorization"].startswith("Basic ")

    headers3 = {}
    apply_auth_helper({"header": "X-API-Key", "key": "key-123"}, headers3)
    assert headers3["x-api-key"] == "key-123"

def test_http_executor_live():
    # Start ephemeral HTTP server on loopback
    server = HTTPServer(("127.0.0.1", 0), MockServerHandler)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        executor = HttpStepExecutor(base_url=base_url)
        ctx = RunContext(run_id="run-http-1", worker_id="w-0", env_profile="test")

        # 1. Successful GET
        step_get = ResolvedStep(id="s1", kind="http", operation="getOrder", method="GET", path="/orders/{id}", params={"id": "123"})
        res_get = executor.execute(step_get, ctx)
        assert res_get.status_code == 200
        assert res_get.data["id"] == "123"
        assert res_get.data["total"] == 49.98
        assert res_get.transport_error is None

        # 2. Authenticated GET
        step_auth = ResolvedStep(id="s2", kind="http", operation="checkAuth", method="GET", path="/auth-check", auth="secret-token")
        res_auth = executor.execute(step_auth, ctx)
        assert res_auth.status_code == 200
        assert res_auth.data["authenticated"] is True

        # 3. HTTP 400 Bad Request is NOT a transport error
        step_bad = ResolvedStep(id="s3", kind="http", operation="createOrder", method="POST", path="/orders", body={"items": []})
        res_bad = executor.execute(step_bad, ctx)
        assert res_bad.status_code == 400
        assert res_bad.transport_error is None
        assert res_bad.data["error"] == "Empty items"

        # 4. HTTP 404 is NOT a transport error
        step_404 = ResolvedStep(id="s4", kind="http", operation="unknown", method="GET", path="/missing")
        res_404 = executor.execute(step_404, ctx)
        assert res_404.status_code == 404
        assert res_404.transport_error is None

        # 5. Target port closed -> transport error
        dead_executor = HttpStepExecutor(base_url="http://127.0.0.1:1")
        res_dead = dead_executor.execute(step_get, ctx)
        assert res_dead.status_code is None
        assert res_dead.transport_error is not None
        assert "refused" in res_dead.transport_error.lower() or "failed" in res_dead.transport_error.lower()

        print("HTTP executor, auth helpers, and JSONPath extraction tests PASSED!")
    finally:
        server.shutdown()

if __name__ == "__main__":
    test_jsonpath_extraction()
    test_auth_helpers()
    test_http_executor_live()

