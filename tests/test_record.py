"""
Tests for minimal trace writer (T2.7, FR-R2 partial).
"""

import sys
from http.server import HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile
import threading
from cairn_test.core.schemas import load_trace
from cairn_test.plugins.api.record import record_test_trace
from cairn_test.plugins.api.spec import OpenAPISpec
from tests.test_api_spec import SAMPLE_SPEC
from tests.test_http_executor import MockServerHandler

def test_record_test_trace():
    # Start mock server
    server = HTTPServer(("127.0.0.1", 0), MockServerHandler)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "traces"

            test_def = {
                "schema": "cairn-test.test/v1",
                "id": "rec-order-test",
                "steps": [
                    {
                        "id": "s1",
                        "op": "getOrder",
                        "args": {"id": "123"},
                    }
                ],
            }

            trace_file = record_test_trace(
                test_def=test_def,
                spec=OpenAPISpec(SAMPLE_SPEC),
                base_url=base_url,
                env_profile="local",
                output_dir=out_dir,
            )

            assert trace_file.is_file()
            # Validate generated trace against cairn-test.trace/v1 JSON schema
            trace_doc = load_trace(trace_file)
            assert trace_doc["test"] == "rec-order-test"
            assert len(trace_doc["steps"]) == 1
            step = trace_doc["steps"][0]
            assert step["id"] == "s1"
            assert step["observation"]["status"] == 200
            assert "total" in step["observation"]["body_shape"]

            print("Minimal trace writer test PASSED!")
    finally:
        server.shutdown()

if __name__ == "__main__":
    test_record_test_trace()
