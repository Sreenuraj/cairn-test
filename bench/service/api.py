"""
Reference stateful Target API with switchable seeded changes (T6.1, T6.2, FR-B1).

Runs as a lightweight HTTPServer with in-memory state for auth, products, orders, and refunds.
Seeded changes can be activated per-request via the header 'X-Seeded-Change' or globally on the server.
"""

from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from typing import Any
import urllib.parse

class StoreService:
    """In-memory stateful store service."""

    def __init__(self):
        self.users = {"alice": "password123", "bob": "secret456"}
        self.tokens = {"alice-token": "alice", "bob-token": "bob"}
        self.products = [
            {"id": "prod-1", "name": "Mechanical Keyboard", "price": 99.0},
            {"id": "prod-2", "name": "Wireless Mouse", "price": 49.98},
            {"id": "prod-3", "name": "USB-C Hub", "price": 29.5},
            {"id": "prod-4", "name": "Monitor Arm", "price": 75.0},
            {"id": "prod-5", "name": "Desk Mat", "price": 19.99},
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
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len == 0:
            return {}
        raw = self.rfile.read(content_len)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_POST(self) -> None:
        seed = self.get_seed()
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path

        # 1. POST /auth/login
        if path == "/auth/login":
            body = self.read_json_body()
            user = body.get("username")
            pwd = body.get("password")
            if user in self.store.users and self.store.users[user] == pwd:
                token = f"{user}-token"
                self.send_json(200, {"token": token, "user": user})
            else:
                self.send_json(401, {"error": "Invalid credentials"})
            return

        # 2. POST /orders
        if path == "/orders":
            if seed in ["C-REQ-2", "CMP-4"]:
                # Endpoint moved to /v2/orders -> returns 404
                self.send_json(404, {"error": "Endpoint moved to /v2/orders"})
                return

            body = self.read_json_body()

            # Seed C-REQ-4: New required parameter delivery_type
            if seed == "C-REQ-4" and "delivery_type" not in body:
                self.send_json(400, {"error": "Missing required field 'delivery_type'"})
                return

            items = body.get("items", [])
            # Seed BUG-2 / CMP-3: missing validation on empty items
            if not items and seed not in ["BUG-2", "CMP-3"]:
                self.send_json(400, {"error": "Items cannot be empty"})
                return

            # Compute total
            total = sum(float(i.get("price", 0)) * int(i.get("qty", 1)) for i in items)

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

            # Seed C-RES-1 / CMP-1 / CMP-2: rename total to grand_total
            if seed in ["C-RES-1", "CMP-1", "CMP-2"]:
                resp_data["grand_total"] = resp_data.pop("total")

            # Seed CMP-1: wrong status bug (preregistration Table 2.5: BUG-1 wrong item status)
            if seed == "CMP-1":
                resp_data["status"] = "PENDING"

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
            self.send_json(201, {
                "id": ref_id,
                "order_id": order_id,
                "amount": amount,
                "status": "APPROVED",
            })
            return

        self.send_json(404, {"error": "Not Found"})

    def do_GET(self) -> None:
        seed = self.get_seed()
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path
        query = urllib.parse.parse_qs(url_parts.query)

        # 1. GET /products
        if path == "/products":
            limit = int(query.get("limit", [10])[0])
            offset = int(query.get("offset", [0])[0])

            # Seed BUG-4: pagination off-by-one bug
            if seed == "BUG-4" and offset > 0:
                offset += 1

            items = self.store.products[offset : offset + limit]
            self.send_json(200, {"items": items, "count": len(items)})
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
