"""
Tests for API assertions with static reads derivation (T2.4, FR-A3).
"""

from cairn_test.contracts import ResolvedStep, RunContext, StepResult
from cairn_test.plugins.api.assertions import (
    HeaderAssertion,
    JsonPathAssertion,
    StateAssertion,
    StatusAssertion,
)

def test_status_assertion():
    a = StatusAssertion()
    assert a.reads({"status": 200}) == ["$.status"]

    ctx = RunContext("run-1", "w-0", "local")
    res_200 = StepResult("s1", status_code=200)
    res_404 = StepResult("s1", status_code=404)

    assert a.evaluate({"status": 200}, res_200, ctx) is True
    assert a.evaluate({"status": 200}, res_404, ctx) is False

def test_header_assertion():
    a = HeaderAssertion()
    assert a.reads({"header": "Content-Type"}) == ["headers.content-type"]
    assert a.reads({"header": {"X-Trace": "1"}}) == ["headers.x-trace"]

    ctx = RunContext("run-1", "w-0", "local")
    res = StepResult("s1", status_code=200, headers={"content-type": "application/json", "etag": "W/123"})

    assert a.evaluate({"header": "Content-Type"}, res, ctx) is True
    assert a.evaluate({"header": "X-Missing"}, res, ctx) is False
    assert a.evaluate({"header": {"ETag": "W/123"}}, res, ctx) is True
    assert a.evaluate({"header": {"ETag": "wrong"}}, res, ctx) is False

def test_jsonpath_assertion_operators():
    a = JsonPathAssertion()
    assert a.reads({"jsonpath": "$.user.total"}) == ["$.user.total"]

    ctx = RunContext("run-1", "w-0", "local")
    res = StepResult("s1", status_code=200, data={
        "total": 49.98,
        "status": "PLACED",
        "count": 5,
        "items": ["SKU-1", "SKU-2"],
    })

    # equals
    assert a.evaluate({"jsonpath": "$.total", "equals": 49.98}, res, ctx) is True
    assert a.evaluate({"jsonpath": "$.total", "equals": 50.00}, res, ctx) is False
    assert a.evaluate({"jsonpath": "$.status", "equals": "PLACED"}, res, ctx) is True

    # matches regex
    assert a.evaluate({"jsonpath": "$.status", "matches": "^PL[A-Z]+$"}, res, ctx) is True
    assert a.evaluate({"jsonpath": "$.status", "matches": "^CANCELLED$"}, res, ctx) is False

    # exists
    assert a.evaluate({"jsonpath": "$.total", "exists": True}, res, ctx) is True
    assert a.evaluate({"jsonpath": "$.missing_field", "exists": False}, res, ctx) is True

    # in
    assert a.evaluate({"jsonpath": "$.status", "in": ["PENDING", "PLACED"]}, res, ctx) is True
    assert a.evaluate({"jsonpath": "$.status", "in": ["CANCELLED", "REFUNDED"]}, res, ctx) is False

    # range
    assert a.evaluate({"jsonpath": "$.count", "range": {"min": 1, "max": 10}}, res, ctx) is True
    assert a.evaluate({"jsonpath": "$.count", "range": {"min": 10, "max": 20}}, res, ctx) is False

    # missing path returns "missing"
    assert a.evaluate({"jsonpath": "$.absent_key", "equals": "val"}, res, ctx) == "missing"

def test_state_assertion():
    class MockStateExecutor:
        def execute(self, step: ResolvedStep, ctx: RunContext) -> StepResult:
            return StepResult(step.id, status_code=200, data={"status": "PLACED"})

    a = StateAssertion(executor=MockStateExecutor())
    assert a.reads({"state": {"op": "getOrder", "jsonpath": "$.status"}}) == ["$.status"]

    ctx = RunContext("run-1", "w-0", "local")
    res = StepResult("s1", status_code=201)

    assert a.evaluate({"state": {"op": "getOrder", "jsonpath": "$.status", "equals": "PLACED"}}, res, ctx) is True
    assert a.evaluate({"state": {"op": "getOrder", "jsonpath": "$.status", "equals": "CANCELLED"}}, res, ctx) is False

if __name__ == "__main__":
    test_status_assertion()
    test_header_assertion()
    test_jsonpath_assertion_operators()
    test_state_assertion()
    print("All T2.4 assertion types tests PASSED!")
