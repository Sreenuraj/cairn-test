"""
Sets up the 12-behavior core suite (B01-B12) in bench/tests and records initial baseline traces in bench/traces.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import threading
import yaml

from bench.service.api import StoreApiHandler, start_reference_server
from cairn_test.plugins.api.record import record_test_trace
from cairn_test.plugins.api.spec import OpenAPISpec

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "bench" / "tests"
TRACES_DIR = REPO_ROOT / "bench" / "traces"
SPEC_FILE = REPO_ROOT / "bench" / "service" / "openapi.yaml"

CORE_BEHAVIORS_TESTS = [
    {
        "schema": "cairn-test.test/v1",
        "id": "B01-auth-login-success",
        "tags": ["auth", "smoke", "core"],
        "steps": [
            {
                "id": "login",
                "op": "login",
                "args": {"body": {"username": "alice", "password": "password123"}},
                "extract": {"token": "$.token"},
            }
        ],
        "expect": [
            {"after": "login", "status": 200},
            {"after": "login", "jsonpath": "$.user", "equals": "alice"},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B02-auth-login-invalid-credentials",
        "tags": ["auth", "negative", "core"],
        "steps": [
            {
                "id": "login_bad",
                "op": "login",
                "args": {"body": {"username": "alice", "password": "wrongpassword"}},
            }
        ],
        "expect": [
            {"after": "login_bad", "status": 401},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B03-products-list",
        "tags": ["products", "core"],
        "steps": [
            {
                "id": "list_products",
                "op": "getProducts",
                "args": {},
            }
        ],
        "expect": [
            {"after": "list_products", "status": 200},
            {"after": "list_products", "jsonpath": "$.count", "range": {"min": 1, "max": 100}},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B04-products-get-by-id",
        "tags": ["products", "core"],
        "steps": [
            {
                "id": "get_product",
                "op": "getProduct",
                "args": {"id": "prod-1"},
            }
        ],
        "expect": [
            {"after": "get_product", "status": 200},
            {"after": "get_product", "jsonpath": "$.id", "equals": "prod-1"},
            {"after": "get_product", "jsonpath": "$.price", "equals": 99.0},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B05-orders-create-single-item",
        "tags": ["orders", "smoke", "core"],
        "steps": [
            {
                "id": "create_order",
                "op": "createOrder",
                "args": {
                    "body": {
                        "ref": "ref-b05",
                        "items": [{"sku": "prod-2", "qty": 1, "price": 49.98}],
                    }
                },
                "extract": {"order_id": "$.id"},
            }
        ],
        "expect": [
            {"after": "create_order", "status": 201},
            {"after": "create_order", "jsonpath": "$.total", "equals": 49.98},
            {"after": "create_order", "jsonpath": "$.status", "equals": "PLACED"},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B06-orders-create-multi-item",
        "tags": ["orders", "core"],
        "steps": [
            {
                "id": "create_multi",
                "op": "createOrder",
                "args": {
                    "body": {
                        "ref": "ref-b06",
                        "items": [
                            {"sku": "prod-1", "qty": 1, "price": 99.0},
                            {"sku": "prod-3", "qty": 1, "price": 29.5},
                        ],
                    }
                },
            }
        ],
        "expect": [
            {"after": "create_multi", "status": 201},
            {"after": "create_multi", "jsonpath": "$.total", "equals": 128.5},
            {"after": "create_multi", "jsonpath": "$.status", "equals": "PLACED"},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B07-orders-get-status",
        "tags": ["orders", "core"],
        "steps": [
            {
                "id": "get_order",
                "op": "getOrder",
                "args": {"id": "ord-seed-1"},
            }
        ],
        "expect": [
            {"after": "get_order", "status": 200},
            {"after": "get_order", "jsonpath": "$.status", "equals": "PLACED"},
            {"after": "get_order", "jsonpath": "$.total", "equals": 49.98},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B08-orders-cancel-unpaid",
        "tags": ["orders", "core"],
        "steps": [
            {
                "id": "cancel_order",
                "op": "cancelOrder",
                "args": {"id": "ord-seed-1"},
            }
        ],
        "expect": [
            {"after": "cancel_order", "status": 200},
            {"after": "cancel_order", "jsonpath": "$.status", "equals": "CANCELLED"},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B09-refunds-request-valid",
        "tags": ["refunds", "core"],
        "steps": [
            {
                "id": "refund",
                "op": "requestRefund",
                "args": {"body": {"order_id": "ord-seed-1", "amount": 20.0}},
            }
        ],
        "expect": [
            {"after": "refund", "status": 201},
            {"after": "refund", "jsonpath": "$.status", "equals": "APPROVED"},
            {"after": "refund", "jsonpath": "$.amount", "equals": 20.0},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B10-compound-step-chain",
        "tags": ["orders", "integration", "core"],
        "steps": [
            {
                "id": "login",
                "op": "login",
                "args": {"body": {"username": "alice", "password": "password123"}},
                "extract": {"token": "$.token"},
            },
            {
                "id": "create",
                "op": "createOrder",
                "auth": "{token}",
                "args": {
                    "body": {
                        "ref": "chain-order",
                        "items": [{"sku": "prod-2", "qty": 1, "price": 49.98}],
                    }
                },
                "extract": {"order_id": "$.id"},
            },
            {
                "id": "get",
                "op": "getOrder",
                "auth": "{token}",
                "args": {"id": "{order_id}"},
            },
        ],
        "expect": [
            {"after": "login", "status": 200},
            {"after": "create", "status": 201},
            {"after": "create", "jsonpath": "$.total", "equals": 49.98},
            {"after": "get", "status": 200},
            {"after": "get", "jsonpath": "$.status", "equals": "PLACED"},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B11-orders-negative-empty-items",
        "tags": ["orders", "negative", "core"],
        "steps": [
            {
                "id": "create_empty",
                "op": "createOrder",
                "args": {"body": {"items": []}},
            }
        ],
        "expect": [
            {"after": "create_empty", "status": 400},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B12-products-nonexistent-404",
        "tags": ["products", "negative", "core"],
        "steps": [
            {
                "id": "get_404",
                "op": "getProduct",
                "args": {"id": "prod-999"},
            }
        ],
        "expect": [
            {"after": "get_404", "status": 404},
        ],
    },
]

def setup_suite():
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    TRACES_DIR.mkdir(parents=True, exist_ok=True)

    spec = OpenAPISpec.load(SPEC_FILE)

    # Start reference server
    server, base_url = start_reference_server(port=0)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        for t_def in CORE_BEHAVIORS_TESTS:
            test_file = TESTS_DIR / f"{t_def['id']}.test.yaml"
            with open(test_file, "w", encoding="utf-8") as f:
                yaml.dump(t_def, f, sort_keys=False)

            # Record baseline trace
            StoreApiHandler.store.reset()
            record_test_trace(
                test_def=t_def,
                spec=spec,
                base_url=base_url,
                env_profile="local",
                output_dir=TRACES_DIR,
            )
            print(f"Recorded trace for {t_def['id']}")

        print(f"\nAll {len(CORE_BEHAVIORS_TESTS)} core behavior tests and traces created successfully!")
    finally:
        server.shutdown()

if __name__ == "__main__":
    setup_suite()
