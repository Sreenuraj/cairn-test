"""
Expands and records the complete 30-behavior benchmark catalog (B01-B30) in bench/tests and bench/traces.
"""

from pathlib import Path
import sys
import threading
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from bench.service.api import StoreApiHandler, start_reference_server
from cairn_test.plugins.api.record import record_test_trace
from cairn_test.plugins.api.spec import OpenAPISpec

TESTS_DIR = REPO_ROOT / "bench" / "tests"
TRACES_DIR = REPO_ROOT / "bench" / "traces"
SPEC_FILE = REPO_ROOT / "bench" / "service" / "openapi.yaml"

ADDITIONAL_BEHAVIORS_TESTS = [
    {
        "schema": "cairn-test.test/v1",
        "id": "B13-auth-refresh-token",
        "tags": ["auth"],
        "steps": [
            {
                "id": "refresh",
                "op": "refresh",
                "args": {"body": {"refresh_token": "token-alice-123"}},
            }
        ],
        "expect": [
            {"after": "refresh", "status": 200},
            {"after": "refresh", "jsonpath": "$.token", "exists": True},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B14-auth-revoke-token",
        "tags": ["auth"],
        "steps": [
            {
                "id": "logout",
                "op": "logout",
                "args": {},
            }
        ],
        "expect": [
            {"after": "logout", "status": 200},
            {"after": "logout", "jsonpath": "$.status", "equals": "logged_out"},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B15-products-filter-by-category",
        "tags": ["products"],
        "steps": [
            {
                "id": "filter",
                "op": "getProducts",
                "args": {"params": {"category": "electronics"}},
            }
        ],
        "expect": [
            {"after": "filter", "status": 200},
            {"after": "filter", "jsonpath": "$.count", "range": {"min": 1}},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B16-products-pagination",
        "tags": ["products"],
        "steps": [
            {
                "id": "paginate",
                "op": "getProducts",
                "args": {"params": {"limit": 5, "offset": 5}},
            }
        ],
        "expect": [
            {"after": "paginate", "status": 200},
            {"after": "paginate", "jsonpath": "$.count", "equals": 5},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B17-products-inventory-check",
        "tags": ["products", "inventory"],
        "steps": [
            {
                "id": "inventory",
                "op": "getInventory",
                "args": {"params": {"id": "prod-1"}},
            }
        ],
        "expect": [
            {"after": "inventory", "status": 200},
            {"after": "inventory", "jsonpath": "$.stock", "equals": 42},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B18-orders-apply-coupon",
        "tags": ["orders", "discounts"],
        "steps": [
            {
                "id": "coupon_order",
                "op": "createOrder",
                "args": {
                    "body": {
                        "items": [{"sku": "prod-1", "qty": 1, "price": 100}],
                        "coupon": "SAVE10",
                    }
                },
            }
        ],
        "expect": [
            {"after": "coupon_order", "status": 201},
            {"after": "coupon_order", "jsonpath": "$.total", "equals": 90.0},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B19-orders-invalid-coupon",
        "tags": ["orders", "negative"],
        "steps": [
            {
                "id": "bad_coupon",
                "op": "createOrder",
                "args": {
                    "body": {
                        "items": [{"sku": "prod-1", "qty": 1, "price": 100}],
                        "coupon": "EXPIRED",
                    }
                },
            }
        ],
        "expect": [
            {"after": "bad_coupon", "status": 422},
            {"after": "bad_coupon", "jsonpath": "$.error", "equals": "Expired coupon code"},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B20-orders-list-user-orders",
        "tags": ["orders"],
        "steps": [
            {
                "id": "user_orders",
                "op": "getOrders",
                "args": {"headers": {"Authorization": "Bearer jwt-token-alice"}},
            }
        ],
        "expect": [
            {"after": "user_orders", "status": 200},
            {"after": "user_orders", "jsonpath": "$.count", "range": {"min": 1}},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B21-orders-isolation-cross-user",
        "tags": ["orders", "security"],
        "steps": [
            {
                "id": "cross_user",
                "op": "getOrder",
                "args": {
                    "params": {"id": "ord-seed-1"},
                    "headers": {"Authorization": "Bearer jwt-token-bob"},
                },
            }
        ],
        "expect": [
            {"after": "cross_user", "status": 403},
            {"after": "cross_user", "jsonpath": "$.error", "equals": "Forbidden"},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B22-orders-update-shipping-address",
        "tags": ["orders"],
        "steps": [
            {
                "id": "update_ship",
                "op": "updateShipping",
                "args": {
                    "params": {"id": "ord-seed-1"},
                    "body": {"address": "123 Main St, New York, NY"},
                },
            }
        ],
        "expect": [
            {"after": "update_ship", "status": 200},
            {"after": "update_ship", "jsonpath": "$.status", "equals": "UPDATED"},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B23-orders-pay-with-card",
        "tags": ["orders", "payments"],
        "steps": [
            {
                "id": "pay",
                "op": "payOrder",
                "args": {"params": {"id": "ord-seed-1"}},
            }
        ],
        "expect": [
            {"after": "pay", "status": 200},
            {"after": "pay", "jsonpath": "$.status", "equals": "PAID"},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B24-orders-duplicate-payment-idempotent",
        "tags": ["orders", "payments"],
        "steps": [
            {
                "id": "idemp_pay",
                "op": "payOrder",
                "args": {
                    "params": {"id": "ord-seed-1"},
                    "headers": {"Idempotency-Key": "idemp-key-repeat-1"},
                },
            }
        ],
        "expect": [
            {"after": "idemp_pay", "status": 200},
            {"after": "idemp_pay", "jsonpath": "$.status", "equals": "PAID"},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B25-refunds-full-order",
        "tags": ["refunds"],
        "steps": [
            {
                "id": "full_refund",
                "op": "requestRefund",
                "args": {
                    "body": {"order_id": "ord-seed-1", "amount": 49.98}
                },
            }
        ],
        "expect": [
            {"after": "full_refund", "status": 201},
            {"after": "full_refund", "jsonpath": "$.status", "equals": "REFUNDED"},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B26-refunds-exceed-order-total",
        "tags": ["refunds", "negative"],
        "steps": [
            {
                "id": "over_refund",
                "op": "requestRefund",
                "args": {
                    "body": {"order_id": "ord-seed-1", "amount": 999.0}
                },
            }
        ],
        "expect": [
            {"after": "over_refund", "status": 400},
            {"after": "over_refund", "jsonpath": "$.error", "exists": True},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B27-customers-get-profile",
        "tags": ["customers"],
        "steps": [
            {
                "id": "cust_me",
                "op": "getCustomer",
                "args": {"headers": {"Authorization": "Bearer jwt-token-alice"}},
            }
        ],
        "expect": [
            {"after": "cust_me", "status": 200},
            {"after": "cust_me", "jsonpath": "$.username", "equals": "alice"},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B28-customers-update-profile",
        "tags": ["customers"],
        "steps": [
            {
                "id": "update_me",
                "op": "updateCustomer",
                "args": {
                    "headers": {"Authorization": "Bearer jwt-token-alice"},
                    "body": {"name": "Alice Wonderland"},
                },
            }
        ],
        "expect": [
            {"after": "update_me", "status": 200},
            {"after": "update_me", "jsonpath": "$.name", "equals": "Alice Wonderland"},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B29-system-health-check",
        "tags": ["system", "smoke"],
        "steps": [
            {
                "id": "health",
                "op": "getHealth",
                "args": {},
            }
        ],
        "expect": [
            {"after": "health", "status": 200},
            {"after": "health", "jsonpath": "$.status", "equals": "HEALTHY"},
        ],
    },
    {
        "schema": "cairn-test.test/v1",
        "id": "B30-system-openapi-spec",
        "tags": ["system"],
        "steps": [
            {
                "id": "spec",
                "op": "getOpenApiSpec",
                "args": {},
            }
        ],
        "expect": [
            {"after": "spec", "status": 200},
            {"after": "spec", "jsonpath": "$.openapi", "equals": "3.1.0"},
        ],
    },
]

def setup_full_suite():
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    TRACES_DIR.mkdir(parents=True, exist_ok=True)

    server, base_url = start_reference_server(port=0)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    spec = OpenAPISpec.load(SPEC_FILE) if SPEC_FILE.is_file() else None

    print(f"Setting up behaviors B13-B30 against reference server at {base_url}...")
    for t_def in ADDITIONAL_BEHAVIORS_TESTS:
        tid = t_def["id"]
        t_file = TESTS_DIR / f"{tid}.test.yaml"
        with open(t_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(t_def, f, sort_keys=False)

        # Record baseline trace
        StoreApiHandler.store.reset()
        trace_path = record_test_trace(
            test_def=t_def,
            base_url=base_url,
            spec=spec,
            env_profile="local",
            output_dir=TRACES_DIR,
        )
        print(f"Recorded baseline trace -> {trace_path.name}")

    server.shutdown()
    print("All 30 benchmark behaviors set up in bench/tests and bench/traces!")

if __name__ == "__main__":
    setup_full_suite()
