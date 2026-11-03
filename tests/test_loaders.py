"""
Tests for schema loaders and validators (T1.2, FR-C1, FR-C2).
"""

from pathlib import Path
from cairn_test.core.schemas import (
    load_test,
    load_trace,
    load_approval,
    load_proposal,
    load_event,
    load_result,
    SchemaValidationError,
    SchemaVersionError,
)

def test_load_test_valid_and_invalid():
    valid = {
        "schema": "cairn-test.test/v1",
        "id": "order-test",
        "steps": [{"id": "s1", "op": "login"}]
    }
    loaded = load_test(valid)
    assert loaded["id"] == "order-test"

    # Missing schema field
    no_schema = {"id": "order-test", "steps": [{"id": "s1", "op": "login"}]}
    try:
        load_test(no_schema)
        assert False, "Expected SchemaValidationError for missing schema"
    except SchemaValidationError as e:
        assert "Missing required 'schema' identifier" in str(e)

    # Unknown schema version with migration hint
    unknown_version = {
        "schema": "cairn-test.test/v2",
        "id": "order-test",
        "steps": [{"id": "s1", "op": "login"}]
    }
    try:
        load_test(unknown_version)
        assert False, "Expected SchemaVersionError"
    except SchemaVersionError as e:
        assert "cairn-test migrate" in str(e)
        assert "Unsupported schema version" in str(e)

    # Invalid document contents
    invalid_content = {
        "schema": "cairn-test.test/v1",
        "id": "order-test",
        "steps": []  # minItems is 1
    }
    try:
        load_test(invalid_content)
        assert False, "Expected SchemaValidationError for empty steps"
    except SchemaValidationError as e:
        assert "Validation error at '$.steps'" in str(e)

def test_load_trace_valid_and_invalid():
    valid = {
        "schema": "cairn-test.trace/v1",
        "test": "order-test",
        "env_profile": "local",
        "spec_hash": "a" * 64,
        "steps": [
            {
                "id": "s1",
                "step_hash": "b" * 64,
                "resolved": {"operation": "login", "method": "POST", "path": "/login"},
                "pre_fingerprint": {"op_hash": "c" * 64},
                "observation": {"status": 200},
                "recorded_at": "2026-11-03T10:00:00Z"
            }
        ]
    }
    loaded = load_trace(valid)
    assert loaded["test"] == "order-test"

    # Wrong schema version
    bad_version = dict(valid, schema="cairn-test.trace/v0")
    try:
        load_trace(bad_version)
        assert False
    except SchemaVersionError as e:
        assert "cairn-test migrate" in str(e)

def test_load_approval_valid_and_invalid():
    valid = {
        "schema": "cairn-test.approval/v1",
        "subject": "order-test",
        "covers": {"tests/order-test.test.yaml": "d" * 64},
        "approver": {"name": "user", "key": "key1", "key_type": "ssh-ed25519"},
        "at": "2026-11-03T10:05:00Z"
    }
    loaded = load_approval(valid)
    assert loaded["subject"] == "order-test"

    bad_kind = dict(valid, schema="cairn-test.trace/v1")
    try:
        load_approval(bad_kind)
        assert False
    except SchemaVersionError as e:
        assert "cairn-test migrate" in str(e)

def test_load_proposal_event_result():
    prop = {
        "schema": "cairn-test.proposal/v1",
        "id": "prop-1",
        "kind": "heal",
        "test": "order-test",
        "created_at": "2026-11-03T10:00:00Z",
        "reason": "Moved path",
        "details": {"step_id": "s1"}
    }
    assert load_proposal(prop)["id"] == "prop-1"

    event = {
        "schema": "cairn-test.event/v1",
        "run_id": "run-1",
        "sequence": 0,
        "timestamp": "2026-11-03T10:00:00Z",
        "type": "run.started",
        "payload": {}
    }
    assert load_event(event)["type"] == "run.started"

    res = {
        "schema": "cairn-test.result/v1",
        "run_id": "run-1",
        "test": "order-test",
        "outcome": "PASS",
        "duration_ms": 12.3,
        "versions": {"framework": "0.1.0", "plugins": {}},
        "recorded_at": "2026-11-03T10:00:01Z"
    }
    assert load_result(res)["outcome"] == "PASS"

if __name__ == "__main__":
    test_load_test_valid_and_invalid()
    test_load_trace_valid_and_invalid()
    test_load_approval_valid_and_invalid()
    test_load_proposal_event_result()
    print("All T1.2 loader and validator tests passed!")
