"""
Tests for Phase 5: Reporting, interface, migrations, doctor, health, and complete explain (T5.1..T5.6, Gate G5).
"""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
import yaml

from cairn_test.core.doctor import Doctor
from cairn_test.core.events import EventBus, EventStore
from cairn_test.core.explain import explain_test
from cairn_test.core.health import HealthAnalyzer
from cairn_test.core.migration import MigrationEngine, register_migration
from cairn_test.core.reporting import generate_html_report, generate_junit_xml

REPO_ROOT = Path(__file__).resolve().parent.parent

def test_junit_xml_export():
    """T5.2 / FR-O5: Test standard JUnit XML generation."""
    verdicts = [
        {"test_id": "test_pass", "outcome": "PASS", "duration_ms": 12.5, "reason": None},
        {"test_id": "test_fail", "outcome": "FAIL", "duration_ms": 25.0, "reason": "Expected status 200, got 500"},
        {"test_id": "test_drift", "outcome": "DRIFT", "duration_ms": 15.0, "reason": "Path changed"},
        {"test_id": "test_error", "outcome": "ERROR", "duration_ms": 5.0, "reason": "unapproved"},
        {"test_id": "test_skip", "outcome": "SKIPPED", "duration_ms": 0.0, "reason": "quarantined"},
    ]

    xml_content = generate_junit_xml("run-12345", verdicts, suite_name="my-suite")
    assert xml_content.startswith("<?xml")

    root = ET.fromstring(xml_content)
    assert root.tag == "testsuites"
    assert root.attrib["tests"] == "5"
    assert root.attrib["failures"] == "2"  # FAIL + DRIFT
    assert root.attrib["errors"] == "1"

    suite = root.find("testsuite")
    assert suite is not None
    assert suite.attrib["name"] == "run-12345"
    assert suite.attrib["skipped"] == "1"

    testcases = suite.findall("testcase")
    assert len(testcases) == 5

    tc_fail = next(tc for tc in testcases if tc.attrib["name"] == "test_fail")
    assert tc_fail.find("failure") is not None
    assert tc_fail.find("failure").attrib["type"] == "BehavioralFailure"

    tc_drift = next(tc for tc in testcases if tc.attrib["name"] == "test_drift")
    assert tc_drift.find("failure") is not None
    assert tc_drift.find("failure").attrib["type"] == "ContractDrift"

    tc_error = next(tc for tc in testcases if tc.attrib["name"] == "test_error")
    assert tc_error.find("error") is not None

    tc_skip = next(tc for tc in testcases if tc.attrib["name"] == "test_skip")
    assert tc_skip.find("skipped") is not None

    print("JUnit XML export (T5.2) verified.")

def test_static_html_report():
    """T5.1 / FR-O1, FR-O5: Test responsive static HTML report generation."""
    verdicts = [
        {"test_id": "test_1", "outcome": "PASS", "duration_ms": 10.0, "reason": ""},
        {"test_id": "test_2", "outcome": "FAIL", "duration_ms": 18.0, "reason": "wrong count"},
    ]
    summary = {
        "run_id": "run-abc",
        "total": 2,
        "passed": 1,
        "failed": 1,
        "drifted": 0,
        "errored": 0,
        "skipped": 0,
        "outcome": "FAIL",
    }
    html = generate_html_report("run-abc", summary, verdicts, metadata={"mode": "strict"})
    assert "<!DOCTYPE html>" in html
    assert "cairn-test Run Report" in html
    assert "run-abc" in html
    assert "test_1" in html
    assert "test_2" in html
    assert "wrong count" in html
    assert "strict" in html
    print("Static HTML report generation (T5.1) verified.")

def test_migration_framework():
    """T5.4 / FR-M1: Test schema migration framework across versions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        old_test_file = tmp_path / "test_legacy.yaml"
        old_data = {
            "schema": "cairn-test.test/v0",
            "id": "legacy_test",
            "steps": [
                {"id": "step_0", "op": "listItems", "timeout": 5}
            ],
            "expect": [{"status": 200}],
        }
        with open(old_test_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(old_data, f)

        engine = MigrationEngine()

        # Dry run
        dry_results = engine.migrate_directory(tmp_path, dry_run=True)
        assert len(dry_results) == 1
        assert dry_results[0].modified is True
        assert dry_results[0].old_version == "cairn-test.test/v0"
        assert dry_results[0].new_version == "cairn-test.test/v1"

        # Verify file untouched in dry run
        with open(old_test_file, "r") as f:
            check_data = yaml.safe_load(f)
        assert check_data["schema"] == "cairn-test.test/v0"

        # Actual migration
        real_results = engine.migrate_directory(tmp_path, dry_run=False)
        assert len(real_results) == 1
        assert real_results[0].modified is True

        # Verify file updated
        with open(old_test_file, "r") as f:
            upgraded = yaml.safe_load(f)
        assert upgraded["schema"] == "cairn-test.test/v1"
        assert upgraded["steps"][0]["timeout_ms"] == 5000
        assert "timeout" not in upgraded["steps"][0]

        print("Schema migration framework (T5.4) verified.")

def test_doctor_diagnostics():
    """T5.6 / FR-V4: Test doctor diagnostics checking key types, trust roots, and CI pinning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        doc = Doctor(repo_root=repo_root)

        # 1. Check CI pinning when no workflow exists
        ci_check = doc.check_ci_pinning()
        assert ci_check.status == "WARN"

        # 2. Add pinned workflow
        wf_dir = repo_root / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        wf_file = wf_dir / "cairn-test.yml"
        wf_file.write_text("uses: actions/checkout@v4\nrun: cairn-test==0.1.0\n")

        ci_check_pinned = doc.check_ci_pinning()
        assert ci_check_pinned.status == "OK"

        # 3. Check trust root
        import os
        old_allowed = os.environ.get("CAIRN_ALLOWED_SIGNERS")
        try:
            os.environ["CAIRN_ALLOWED_SIGNERS"] = "admin ssh-ed25519 AAAAC3..."
            tr_check = doc.check_trust_root()
            assert tr_check.status == "OK"
        finally:
            if old_allowed:
                os.environ["CAIRN_ALLOWED_SIGNERS"] = old_allowed
            else:
                os.environ.pop("CAIRN_ALLOWED_SIGNERS", None)

        print("Doctor diagnostics (T5.6) verified.")

def test_health_analyzer():
    """T5.5 / FR-O4: Test health view, drift rate, flakiness, and quarantine."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        store = EventStore(base_dir=repo_root / ".cairn-test")

        # Create tests with one quarantined test
        tests_dir = repo_root / "tests"
        tests_dir.mkdir(parents=True)
        t1 = tests_dir / "t1.test.yaml"
        t1.write_text("schema: cairn-test.test/v1\nid: t1\nsteps: [{id: s0, op: op1}]\nexpect: [{status: 200}]\n")
        t2 = tests_dir / "t2.test.yaml"
        t2.write_text("schema: cairn-test.test/v1\nid: t2\nquarantine: true\nsteps: [{id: s0, op: op2}]\nexpect: [{status: 200}]\n")

        # Record events for run 1 and run 2 to simulate flakiness and drift
        bus1 = EventBus(run_id="run-1", store=store)
        bus1.emit("test.finished", {"test_id": "t1", "outcome": "PASS"})

        bus2 = EventBus(run_id="run-2", store=store)
        bus2.emit("test.finished", {"test_id": "t1", "outcome": "DRIFT"})

        analyzer = HealthAnalyzer(repo_root=repo_root, store=store)
        health = analyzer.analyze()

        assert health.total_tests == 2
        assert len(health.quarantined_tests) == 1
        assert health.quarantined_tests[0]["test_id"] == "t2"
        assert "t1" in health.flaky_tests, "t1 exhibited both PASS and DRIFT, must be flaky"
        assert health.drift_rate_percent == 50.0  # 1 out of 2 tests latest outcome DRIFT

        print("Health view analyzer (T5.5) verified.")

def test_complete_explain_from_stored_artifacts():
    """
    T5.3 / FR-G2, FR-O7 / Gate G5:
    Verifies that for every outcome and reason code, complete structured explanations
    can be regenerated from stored artifacts alone.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        store = EventStore(base_dir=repo_root / ".cairn-test")

        run_id = "run-explain-test"
        bus = EventBus(run_id=run_id, store=store)

        # 1. Planned test
        bus.emit("test.planned", {"test_id": "test_quarantined", "action": "SKIPPED", "reason": "quarantined"})

        # Record results in database
        import sqlite3
        with sqlite3.connect(store.db_path) as conn:
            conn.execute(
                """INSERT INTO results (run_id, test_id, outcome, reason, duration_ms, versions, drift_detail, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    "test_strict_tampered",
                    "ERROR",
                    "tampered",
                    0.5,
                    "{}",
                    "{}",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.execute(
                """INSERT INTO results (run_id, test_id, outcome, reason, duration_ms, versions, drift_detail, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    "test_contract_drift",
                    "DRIFT",
                    "breaking_paths",
                    12.0,
                    "{}",
                    '{"breaking_paths": ["$.total"]}',
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

        # Explain skipped quarantined test
        exp_skip = explain_test(run_id, "test_quarantined", store=store)
        assert exp_skip["outcome"] == "SKIPPED"
        assert "quarantined" in exp_skip["explanation"]

        # Explain tampered strict failure
        exp_tamper = explain_test(run_id, "test_strict_tampered", store=store)
        assert exp_tamper["outcome"] == "ERROR"
        assert "Content hash mismatch" in exp_tamper["explanation"]

        # Explain drift with breaking paths
        exp_drift = explain_test(run_id, "test_contract_drift", store=store)
        assert exp_drift["outcome"] == "DRIFT"
        assert "$.total" in exp_drift["explanation"]

        print("Complete explain from stored artifacts (T5.3 / Gate G5) verified.")

def test_parameterization_and_fixtures():
    """T5.10 / FR-C17: Test fixtures (setup/teardown) and parameterized test expansion."""
    from cairn_test.core.planner import Planner

    test_def = {
        "schema": "cairn-test.test/v1",
        "id": "param_test",
        "fixtures": {
            "setup": [{"id": "setup_step", "op": "resetDb"}],
            "teardown": [{"id": "teardown_step", "op": "cleanupDb"}],
        },
        "parametrize": {
            "params": ["category", "limit"],
            "cases": [
                ["electronics", 5],
                ["books", 10],
            ],
        },
        "steps": [
            {"id": "exec_step", "op": "searchProducts"}
        ],
        "expect": [{"status": 200}],
    }

    planner = Planner()
    planned = planner.plan_suite([test_def])

    assert len(planned) == 2, f"Expected 2 expanded test cases, got {len(planned)}"
    assert planned[0].test_id == "param_test[0]"
    assert planned[1].test_id == "param_test[1]"

    # Verify parameters bound in data
    assert planned[0].test_def["data"]["category"] == "electronics"
    assert planned[0].test_def["data"]["limit"] == 5
    assert planned[1].test_def["data"]["category"] == "books"
    assert planned[1].test_def["data"]["limit"] == 10

    # Verify fixture steps prepended and appended
    steps_0 = [s["id"] for s in planned[0].test_def["steps"]]
    assert steps_0 == ["setup_step", "exec_step", "teardown_step"]

    print("Parameterization and fixtures (T5.10 / FR-C17) verified.")

def test_property_assertion():
    """T5.9 / FR-A9: Test CEL/expression property assertion."""
    from cairn_test.contracts import StepResult, RunContext
    from cairn_test.plugins.api.assertions import PropertyAssertion

    pa = PropertyAssertion()
    res = StepResult(
        step_id="step_0",
        status_code=200,
        headers={"content-type": "application/json"},
        data={"items": [{"price": 10}, {"price": 20}], "total": 30},
    )
    ctx = RunContext(run_id="run-1", worker_id="w-0", env_profile="local", variables={})

    # Test true expression
    assert pa.evaluate({"property": "body['total'] == 30"}, res, ctx) is True
    assert pa.evaluate({"property": "sum(i['price'] for i in body['items']) == body['total']"}, res, ctx) is True

    # Test false expression
    assert pa.evaluate({"property": "body['total'] == 50"}, res, ctx) is False

    print("Property assertion (T5.9 / FR-A9) verified.")

def test_deterministic_draft():
    """T5.8 / FR-A8: Test deterministic test drafting from spec."""
    from cairn_test.core.draft import SpecDrafter
    from cairn_test.plugins.api.spec import OpenAPISpec

    spec = OpenAPISpec.load(REPO_ROOT / "bench" / "service" / "openapi.yaml")
    drafter = SpecDrafter(spec)
    with tempfile.TemporaryDirectory() as tmpdir:
        created = drafter.draft_suite(Path(tmpdir))
        assert len(created) > 0
        assert all(p.is_file() for p in created)

    print("Deterministic draft (T5.8 / FR-A8) verified.")

def test_mcp_server():
    """T5.7 / FR-G3: Test MCP server over internal API."""
    from cairn_test.core.mcp_server import McpServer, TOOLS

    assert len(TOOLS) == 5
    mcp = McpServer()

    # Test cairn_status tool call
    res_status = mcp.handle_call_tool("cairn_status", {})
    assert "drift_rate_percent" in res_status

    # Test cairn_propose tool call
    res_prop = mcp.handle_call_tool("cairn_propose", {})
    assert "proposals" in res_prop

    print("MCP server over internal API (T5.7 / FR-G3) verified.")

if __name__ == "__main__":
    test_junit_xml_export()
    test_static_html_report()
    test_migration_framework()
    test_doctor_diagnostics()
    test_health_analyzer()
    test_complete_explain_from_stored_artifacts()
    test_parameterization_and_fixtures()
    test_property_assertion()
    test_deterministic_draft()
    test_mcp_server()
    print("\nAll Phase 5 Reporting and Observability tests passed successfully!")
