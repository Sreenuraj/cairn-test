"""
Reference Target API implementation for cairn-test benchmark (T6.1, FR-B1).
A stateful, 12-endpoint e-commerce store API with switchable seeded changes (FR-B1).

Supported Seeded Changes:
- C-REQ-1: status moved from query to body (POST /orders/search)
- C-REQ-2: endpoint /orders moved to /v2/orders (returns 404 on recorded path)
- C-REQ-3: operationId renamed createOrder -> placeOrder
- C-REQ-4: new required parameter delivery_type (returns 400 if missing)
- C-RES-1: total renamed to grand_total
- C-RES-2: customer_id moved to nested customer.id
- C-RES-3: total returned as string ("49.98")
- C-RES-4: endpoint GET /products/{id}/inventory removed (returns 404)
- BUG-1: wrong total calculation (adds 10% tax incorrectly)
- BUG-2: missing validation (accepts empty items array)
- BUG-3: auth bypass (returns order belonging to another customer)
- BUG-4: pagination off-by-one bug
- BUG-5: refund limit logic broken (allows refund > total)
- BEN-1: benign additive field tracking_hint in order response
- BEN-2: benign JSON key order scrambled
- BEN-3: millisecond precision added to timestamp strings
- CMP-1: C-RES-1 (total renamed) + BUG-1 (wrong calculation)
- CMP-2: C-RES-1 (total renamed) + BUG-1 on calculation
- CMP-3: BEN-1 (additive field) + BUG-2 (empty items allowed)
- CMP-4: C-REQ-2 (endpoint moved) blocks downstream step extraction
"""

from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from typing import Any
import urllib.parse
import yaml

class StoreService:
    def __init__(self):
        self.users = {"alice": "password123", "bob": "secret456"}
        self.tokens = {
            "alice-token": "alice",
            "bob-token": "bob",
            "jwt-token-alice": "alice",
            "jwt-token-bob": "bob",
        }
        self.customers = {
            "alice": {
                "id": "cust-alice",
                "username": "alice",
                "email": "alice@example.com",
                "name": "Alice Smith",
                "preference": "email",
            },
            "bob": {
                "id": "cust-bob",
                "username": "bob",
                "email": "bob@example.com",
                "name": "Bob Jones",
                "preference": "sms",
            },
        }
        self.products = [
            {"id": "prod-1", "name": "Mechanical Keyboard", "price": 99.0, "category": "electronics", "stock": 42},
            {"id": "prod-2", "name": "Wireless Mouse", "price": 49.98, "category": "electronics", "stock": 15},
            {"id": "prod-3", "name": "USB-C Hub", "price": 29.5, "category": "electronics", "stock": 50},
            {"id": "prod-4", "name": "Desk Mat", "price": 19.99, "category": "accessories", "stock": 100},
            {"id": "prod-5", "name": "Monitor Stand", "price": 39.99, "category": "accessories", "stock": 30},
            {"id": "prod-6", "name": "Clean Code Book", "price": 35.00, "category": "books", "stock": 20},
            {"id": "prod-7", "name": "Refactoring Book", "price": 40.00, "category": "books", "stock": 18},
            {"id": "prod-8", "name": "Design Patterns", "price": 45.00, "category": "books", "stock": 12},
            {"id": "prod-9", "name": "Ergonomic Chair", "price": 299.99, "category": "furniture", "stock": 5},
            {"id": "prod-10", "name": "Desk Lamp", "price": 24.99, "category": "furniture", "stock": 40},
        ]
        self.orders: dict[str, dict[str, Any]] = {
            "ord-seed-1": {
                "id": "ord-seed-1",
                "user": "alice",
                "ref": "seed-order-1",
                "items": [{"sku": "prod-2", "qty": 1, "price": 49.98}],
                "total": 49.98,
                "status": "PLACED",
            }
        }
        self.refunds: dict[str, dict[str, Any]] = {}
        self.idempotency_keys: dict[str, dict[str, Any]] = {}
        self.active_seed: str | None = None

    def reset(self):
        self.__init__()

class StoreApiHandler(BaseHTTPRequestHandler):
    store = StoreService()

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Quiet logs during test execution

    def get_seed(self) -> str | None:
        return self.headers.get("X-Seeded-Change") or self.store.active_seed

    def send_json(self, status: int, data: Any, extra_headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        body = json.dumps(data)
        self.wfile.write(body.encode("utf-8"))

    def get_authenticated_user(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
            return self.store.tokens.get(token)
        return None

    def read_json_body(self) -> dict[str, Any]:
        if hasattr(self, "_cached_body"):
            return self._cached_body
        length_hdr = self.headers.get("Content-Length")
        if not length_hdr:
            self._cached_body = {}
            return self._cached_body
        try:
            length = int(length_hdr)
            raw = self.rfile.read(length)
            self._cached_body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            self._cached_body = {}
        return self._cached_body

    def do_POST(self) -> None:
        seed = self.get_seed()
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path
        body = self.read_json_body()

        # 1. POST /auth/login
        if path == "/auth/login":
            username = body.get("username")
            password = body.get("password")

            if username in self.store.users and self.store.users[username] == password:
                token = f"jwt-token-{username}"
                self.store.tokens[token] = username
                self.send_json(200, {
                    "token": token,
                    "user": username,
                    "expires_in": 3600,
                })
            else:
                self.send_json(401, {"error": "Invalid username or password"})
            return

        # POST /auth/refresh
        if path == "/auth/refresh":
            body = self.read_json_body()
            ref_token = body.get("refresh_token")
            if ref_token:
                new_token = f"refreshed-jwt-{ref_token}"
                self.store.tokens[new_token] = "alice"
                self.send_json(200, {"token": new_token, "expires_in": 3600})
            else:
                self.send_json(400, {"error": "Missing refresh_token"})
            return

        # POST /auth/logout
        if path == "/auth/logout":
            self.send_json(200, {"status": "logged_out"})
            return

        # 2. POST /orders
        if path == "/orders":
            # Seed C-REQ-2 / CMP-4: Endpoint moved to /v2/orders
            if seed in ["C-REQ-2", "CMP-4"]:
                self.send_json(404, {"error": "Endpoint moved to /v2/orders"})
                return

            body = self.read_json_body()

            # Seed C-REQ-4: New required parameter delivery_type
            if seed == "C-REQ-4" and "delivery_type" not in body:
                self.send_json(400, {"error": "Missing required field 'delivery_type'"})
                return

            # Coupon validation (B18, B19)
            coupon = body.get("coupon")
            if coupon == "EXPIRED":
                self.send_json(422, {"error": "Expired coupon code"})
                return

            items = body.get("items", [])
            # Seed BUG-2 / CMP-3: missing validation on empty items
            if not items and seed not in ["BUG-2", "CMP-3"]:
                self.send_json(400, {"error": "Items cannot be empty"})
                return

            total = sum(float(i.get("price", 0)) * int(i.get("qty", 1)) for i in items)
            if coupon == "SAVE10":
                total = round(total * 0.90, 2)

            # Seed BUG-1 / CMP-1: wrong total bug (adds 10% tax incorrectly)
            if seed in ["BUG-1", "CMP-1", "CMP-2"]:
                total = round(total * 1.10, 2)

            order_id = f"ord-{len(self.store.orders) + 1}"
            auth_user = self.get_authenticated_user() or "guest"
            order_record = {
                "id": order_id,
                "user": auth_user,
                "ref": body.get("ref", f"ref-{order_id}"),
                "items": items,
                "total": total,
                "status": "PLACED",
            }
            self.store.orders[order_id] = order_record

            resp_data: dict[str, Any] = {
                "id": order_id,
                "total": total,
                "status": "PLACED",
            }

            # Seed C-RES-1 / CMP-1: total renamed to grand_total
            if seed in ["C-RES-1", "CMP-1", "CMP-2"]:
                resp_data["grand_total"] = resp_data.pop("total")
                if seed in ["CMP-1", "CMP-2"]:
                    resp_data["status"] = "PENDING"
                    order_record["status"] = "PENDING"

            # Seed C-RES-3: total returned as string
            if seed == "C-RES-3":
                resp_data["total"] = str(resp_data["total"])

            # Seed BEN-1 / CMP-3: benign additive field
            if seed in ["BEN-1", "CMP-3"]:
                resp_data["tracking_hint"] = "TRK-SEED-999"

            self.send_json(201, resp_data)
            return

        # POST /v2/orders (for C-REQ-2 heal verification)
        if path == "/v2/orders":
            body = self.read_json_body()
            items = body.get("items", [])
            total = sum(float(i.get("price", 0)) * int(i.get("qty", 1)) for i in items)
            order_id = f"ord-{len(self.store.orders) + 1}"
            self.send_json(201, {"id": order_id, "total": total, "status": "PLACED"})
            return

        # POST /orders/search (for C-REQ-1)
        if path == "/orders/search":
            body = self.read_json_body()
            status = body.get("status", "PLACED")
            results = [o for o in self.store.orders.values() if o.get("status") == status]
            self.send_json(200, {"items": results, "count": len(results)})
            return

        # 3. POST /orders/{id}/cancel
        m_cancel = re.match(r"^/orders/([^/]+)/cancel$", path)
        if m_cancel:
            order_id = m_cancel.group(1)
            order = self.store.orders.get(order_id)
            if not order:
                self.send_json(404, {"error": "Order not found"})
                return
            order["status"] = "CANCELLED"
            self.send_json(200, {"id": order_id, "status": "CANCELLED"})
            return

        # POST /orders/{id}/pay (B23, B24)
        m_pay = re.match(r"^/orders/([^/]+)/pay$", path)
        if m_pay:
            order_id = m_pay.group(1)
            order = self.store.orders.get(order_id)
            if not order:
                self.send_json(404, {"error": "Order not found"})
                return

            idemp_key = self.headers.get("Idempotency-Key")
            if idemp_key and idemp_key in self.store.idempotency_keys:
                self.send_json(200, self.store.idempotency_keys[idemp_key])
                return

            order["status"] = "PAID"
            pay_resp = {"id": order_id, "status": "PAID", "paid_amount": order["total"]}
            if idemp_key:
                self.store.idempotency_keys[idemp_key] = pay_resp
            self.send_json(200, pay_resp)
            return

        # 4. POST /refunds
        if path == "/refunds":
            body = self.read_json_body()
            order_id = body.get("order_id")
            amount = float(body.get("amount", 0.0))
            order = self.store.orders.get(order_id)

            if not order:
                self.send_json(404, {"error": "Order not found"})
                return

            # Seed BUG-5: refund over limit allowed
            if amount > order["total"] and seed != "BUG-5":
                self.send_json(400, {"error": "Refund exceeds order total"})
                return

            ref_id = f"ref-{len(self.store.refunds) + 1}"
            final_status = "REFUNDED" if amount >= order["total"] else "APPROVED"
            ref_record = {
                "id": ref_id,
                "order_id": order_id,
                "amount": amount,
                "status": final_status,
            }
            self.store.refunds[ref_id] = ref_record
            self.send_json(201, ref_record)
            return

        self.send_json(404, {"error": "Not Found"})

    def do_PUT(self) -> None:
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path
        body = self.read_json_body()

        # PUT /orders/{id}/shipping (B22)
        m_ship = re.match(r"^/orders/([^/]+)/shipping$", path)
        if m_ship:
            order_id = m_ship.group(1)
            order = self.store.orders.get(order_id)
            if not order:
                self.send_json(404, {"error": "Order not found"})
                return
            order["shipping_address"] = body.get("address", "")
            self.send_json(200, {"id": order_id, "status": "UPDATED", "shipping_address": order["shipping_address"]})
            return

        self.send_json(404, {"error": "Not Found"})

    def do_PATCH(self) -> None:
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path
        body = self.read_json_body()

        # PATCH /customers/me (B28)
        if path == "/customers/me":
            user = self.get_authenticated_user() or "alice"
            cust = self.store.customers.get(user)
            if not cust:
                self.send_json(404, {"error": "Customer not found"})
                return
            if "name" in body:
                cust["name"] = body["name"]
            if "preference" in body:
                cust["preference"] = body["preference"]
            self.send_json(200, cust)
            return

        self.send_json(404, {"error": "Not Found"})

    def do_GET(self) -> None:
        seed = self.get_seed()
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path
        query = urllib.parse.parse_qs(url_parts.query)

        # GET /health (B29)
        if path == "/health":
            self.send_json(200, {"status": "HEALTHY", "components": {"database": "UP", "cache": "UP"}})
            return

        # GET /openapi.json (B30)
        if path == "/openapi.json":
            spec_file = Path(__file__).parent / "openapi.yaml"
            if spec_file.is_file():
                with open(spec_file) as f:
                    spec_data = yaml.safe_load(f)
                self.send_json(200, spec_data)
            else:
                self.send_json(200, {"openapi": "3.0.0", "info": {"title": "Store API"}})
            return

        # GET /customers/me (B27)
        if path == "/customers/me":
            user = self.get_authenticated_user() or "alice"
            cust = self.store.customers.get(user)
            if cust:
                self.send_json(200, cust)
            else:
                self.send_json(404, {"error": "Customer not found"})
            return

        # 1. GET /products
        if path == "/products":
            items = list(self.store.products)
            # Category filter (B15)
            if "category" in query:
                cat = query["category"][0]
                items = [p for p in items if p.get("category") == cat]

            limit = int(query.get("limit", [10])[0])
            offset = int(query.get("offset", [0])[0])

            # Seed BUG-4: pagination off-by-one bug
            if seed == "BUG-4" and offset > 0:
                offset += 1

            paged = items[offset : offset + limit]
            self.send_json(200, {"items": paged, "count": len(paged)})
            return

        # GET /products/{id}/inventory (B17)
        m_inv = re.match(r"^/products/([^/]+)/inventory$", path)
        if m_inv:
            prod_id = m_inv.group(1)
            # Seed C-RES-4: endpoint removed
            if seed == "C-RES-4":
                self.send_json(404, {"error": "Endpoint removed"})
                return
            prod = next((p for p in self.store.products if p["id"] == prod_id), None)
            if prod:
                self.send_json(200, {"product_id": prod_id, "stock": prod.get("stock", 42)})
            else:
                self.send_json(404, {"error": "Product not found"})
            return

        # 2. GET /products/{id}
        m_prod = re.match(r"^/products/([^/]+)$", path)
        if m_prod:
            prod_id = m_prod.group(1)
            prod = next((p for p in self.store.products if p["id"] == prod_id), None)
            if prod:
                self.send_json(200, prod)
            else:
                self.send_json(404, {"error": "Product not found"})
            return

        # GET /orders (B20)
        if path == "/orders":
            auth_user = self.get_authenticated_user() or "alice"
            user_orders = [o for o in self.store.orders.values() if o.get("user") == auth_user]
            self.send_json(200, {"orders": user_orders, "count": len(user_orders)})
            return

        # 3. GET /orders/{id}
        m_order = re.match(r"^/orders/([^/]+)$", path)
        if m_order:
            order_id = m_order.group(1)
            order = self.store.orders.get(order_id)
            if not order:
                self.send_json(404, {"error": "Order not found"})
                return

            auth_user = self.get_authenticated_user()
            # Seed BUG-3: auth bypass
            if auth_user and order["user"] != "guest" and order["user"] != auth_user and seed != "BUG-3":
                self.send_json(403, {"error": "Forbidden"})
                return

            resp = dict(order)
            # Seed C-RES-1 / CMP-1: field rename
            if seed in ["C-RES-1", "CMP-1", "CMP-2"]:
                resp["grand_total"] = resp.pop("total")

            # Seed C-RES-2: move customer_id into nested customer.id
            if seed == "C-RES-2":
                resp["customer"] = {"id": resp.pop("user", "guest")}

            # Seed C-RES-3: total returned as string
            if seed == "C-RES-3":
                resp["total"] = str(resp["total"])

            self.send_json(200, resp)
            return

        self.send_json(404, {"error": "Not Found"})

def start_reference_server(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", port), StoreApiHandler)
    host, p = server.server_address
    url = f"http://{host}:{p}"
    return server, url
