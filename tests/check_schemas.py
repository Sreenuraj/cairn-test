"""
Verification check for T0.2: validates all 6 JSON schemas against valid plan.md examples
and verifies rejection of invalid examples with useful messages.
"""

import json
from pathlib import Path
import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"

def load_schema(name: str) -> dict:
    with open(SCHEMAS_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)

def test_test_schema():
    schema = load_schema("test.v1.json")
    
    # Valid example from plan.md section 8
    valid_yaml = """
schema: cairn-test.test/v1
id: create-order
tags: [orders, smoke]
data:
  customer: { from: "data/customers.yaml#guest" }
  order_ref: "{run.uid}-order"
steps:
  - id: login
    op: login
    args: { user: "{customer.user}", password: "{customer.password}" }
    extract: { token: "$.token" }
  - id: create
    op: createOrder
    auth: "{token}"
    args: { body: { ref: "{order_ref}", items: [{ sku: "SKU-123", qty: 2 }] } }
    extract: { order_id: "$.id" }
expect:
  - after: create
    status: 201
  - after: create
    jsonpath: "$.total"
    equals: 49.98
  - after: create
    schema: from-spec
  - state:
      op: getOrder
      args: { id: "{order_id}" }
      jsonpath: "$.status"
      equals: PLACED
  - after: create
    property: "body.total == body.items.map(i, i.price * i.qty).sum()"
"""
    valid_doc = yaml.safe_load(valid_yaml)
    jsonschema.validate(instance=valid_doc, schema=schema)

    # Invalid: missing required steps
    invalid_doc = {"schema": "cairn-test.test/v1", "id": "test-1"}
    try:
        jsonschema.validate(instance=invalid_doc, schema=schema)
        assert False, "Expected validation failure for missing steps"
    except jsonschema.ValidationError as e:
        assert "'steps' is a required property" in str(e)

    # Invalid: wrong schema identifier
    invalid_schema_id = {"schema": "cairn-test.test/v2", "id": "test-1", "steps": [{"id": "s1", "op": "op1"}]}
    try:
        jsonschema.validate(instance=invalid_schema_id, schema=schema)
        assert False, "Expected validation failure for schema identifier"
    except jsonschema.ValidationError as e:
        assert "'cairn-test.test/v1'" in str(e)

def test_trace_schema():
    schema = load_schema("trace.v1.json")
    
    valid_yaml = """
schema: cairn-test.trace/v1
test: create-order
env_profile: staging
spec_hash: "a77c445566778899001122334455667788990011223344556677889900112233"
steps:
  - id: create
    step_hash: "9f2c445566778899001122334455667788990011223344556677889900112233"
    resolved:
      operation: createOrder
      method: POST
      path: /orders
      params: { body: [ref, items] }
      headers: { authorization: bearer }
    pre_fingerprint: { op_hash: "c40e445566778899001122334455667788990011223344556677889900112233" }
    observation:
      status: 201
      headers: [content-type, location]
      body_shape: { id: string, total: number, items: [ { sku: string, qty: integer, price: number } ] }
    recorded_at: "2026-11-02T10:00:00Z"
"""
    valid_doc = yaml.safe_load(valid_yaml)
    jsonschema.validate(instance=valid_doc, schema=schema)

    # Invalid: invalid HTTP method
    invalid_doc = yaml.safe_load(valid_yaml)
    invalid_doc["steps"][0]["resolved"]["method"] = "INVALID_METHOD"
    try:
        jsonschema.validate(instance=invalid_doc, schema=schema)
        assert False, "Expected validation failure for invalid method"
    except jsonschema.ValidationError as e:
        assert "INVALID_METHOD" in str(e)

def test_approval_schema():
    schema = load_schema("approval.v1.json")
    
    valid_yaml = """
schema: cairn-test.approval/v1
subject: create-order
covers:
  tests/create-order.test.yaml: "1d4e445566778899001122334455667788990011223344556677889900112233"
  traces/create-order.trace.yaml: "88a0445566778899001122334455667788990011223344556677889900112233"
  data/customers.yaml: "0b7c445566778899001122334455667788990011223344556677889900112233"
  cairn-test.yaml: "5f21445566778899001122334455667788990011223344556677889900112233"
  plugins/discount_rule.py: "9e3a445566778899001122334455667788990011223344556677889900112233"
approver: { name: you, key: "SHA256:Xk3...", key_type: "sk-ssh-ed25519@openssh.com" }
at: "2026-11-02T10:05:00Z"
labels: [new-test]
"""
    valid_doc = yaml.safe_load(valid_yaml)
    jsonschema.validate(instance=valid_doc, schema=schema)

    # Invalid: empty covers
    invalid_doc = yaml.safe_load(valid_yaml)
    invalid_doc["covers"] = {}
    try:
        jsonschema.validate(instance=invalid_doc, schema=schema)
        assert False, "Expected validation failure for empty covers"
    except jsonschema.ValidationError as e:
        assert "minProperties" in str(e) or "should be non-empty" in str(e)

def test_proposal_schema():
    schema = load_schema("proposal.v1.json")
    
    valid_doc = {
        "schema": "cairn-test.proposal/v1",
        "id": "prop-order-heal-1",
        "kind": "heal",
        "test": "create-order",
        "created_at": "2026-11-02T10:15:00Z",
        "reason": "Operation endpoint moved from /v1/orders to /v2/orders",
        "status": "pending",
        "details": {
            "step_id": "create",
            "old_resolved": {"path": "/v1/orders"},
            "new_resolved": {"path": "/v2/orders"},
            "dry_run": {"$.total": "true"}
        }
    }
    jsonschema.validate(instance=valid_doc, schema=schema)

    # Invalid: unknown proposal kind
    invalid_doc = dict(valid_doc)
    invalid_doc["kind"] = "magic-fix"
    try:
        jsonschema.validate(instance=invalid_doc, schema=schema)
        assert False, "Expected validation failure for unknown kind"
    except jsonschema.ValidationError as e:
        assert "magic-fix" in str(e)

def test_event_schema():
    schema = load_schema("event.v1.json")
    
    valid_doc = {
        "schema": "cairn-test.event/v1",
        "run_id": "run-20261102-123456",
        "sequence": 1,
        "timestamp": "2026-11-02T10:00:01Z",
        "type": "observation.diffed",
        "payload": {
            "test_id": "create-order",
            "step_id": "create",
            "diff_class": "additive",
            "changes": [{"path": "$.created_at", "kind": "additive"}]
        }
    }
    jsonschema.validate(instance=valid_doc, schema=schema)

    # Invalid: negative sequence or invalid event type
    invalid_doc = dict(valid_doc)
    invalid_doc["type"] = "user.clicked"
    try:
        jsonschema.validate(instance=invalid_doc, schema=schema)
        assert False, "Expected validation failure for invalid event type"
    except jsonschema.ValidationError as e:
        assert "user.clicked" in str(e)

def test_result_schema():
    schema = load_schema("result.v1.json")
    
    valid_doc = {
        "schema": "cairn-test.result/v1",
        "run_id": "run-20261102-123456",
        "test": "create-order",
        "outcome": "DRIFT",
        "duration_ms": 42.5,
        "reason": "breaking-observation:$.status",
        "drift_detail": {
            "breaking_paths": ["$.status"]
        },
        "expectations": [
            {"after": "create", "kind": "status", "value": "unevaluable", "reason": "breaking-observation:$.status"}
        ],
        "versions": {
            "framework": "0.1.0",
            "plugins": {"http": "0.1.0"}
        },
        "recorded_at": "2026-11-02T10:00:02Z"
    }
    jsonschema.validate(instance=valid_doc, schema=schema)

    # Invalid outcome (e.g. CACHED-PASS is deferred, not in v1 outcome enum)
    invalid_doc = dict(valid_doc)
    invalid_doc["outcome"] = "UNKNOWN_VERDICT"
    try:
        jsonschema.validate(instance=invalid_doc, schema=schema)
        assert False, "Expected validation failure for unknown outcome"
    except jsonschema.ValidationError as e:
        assert "UNKNOWN_VERDICT" in str(e)

if __name__ == "__main__":
    test_test_schema()
    test_trace_schema()
    test_approval_schema()
    test_proposal_schema()
    test_event_schema()
    test_result_schema()
    print("All 6 JSON Schemas passed validation against plan.md examples and rejected invalid examples!")
