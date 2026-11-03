"""
Tests for CLI run command, exit codes, and JSON reporting (T1.10, FR-C9, FR-G1).
"""

import json
import subprocess
import tempfile
from pathlib import Path
import yaml

def create_test_file(tests_dir: Path, test_id: str, outcome_spec: dict) -> Path:
    p = tests_dir / f"{test_id}.test.yaml"
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump({
            "schema": "cairn-test.test/v1",
            "id": test_id,
            "steps": [{"id": "s1", "kind": "fake", "op": "step1", "args": outcome_spec.get("args", {})}],
            "expect": [{"after": "s1", "fake": outcome_spec.get("fake", {"reads": ["$.status"], "evaluate": True})}],
        }, f)
    return p

def create_trace_file(traces_dir: Path, test_id: str, obs_status: int = 200) -> Path:
    p = traces_dir / f"{test_id}.trace.yaml"
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump({
            "schema": "cairn-test.trace/v1",
            "test": test_id,
            "env_profile": "local",
            "spec_hash": "a" * 64,
            "steps": [{
                "id": "s1",
                "step_hash": "b" * 64,
                "resolved": {"operation": "step1", "method": "GET", "path": "/step1"},
                "pre_fingerprint": {"op_hash": "hash-step1"},
                "observation": {"status": obs_status, "body_shape": {"val": "int"}},
                "recorded_at": "2026-11-03T10:00:00Z",
            }],
        }, f)
    return p

def test_cli_exit_codes_and_json():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        tests_dir = base / "tests"
        traces_dir = base / "traces"
        tests_dir.mkdir()
        traces_dir.mkdir()

        # 1. PASS test
        create_test_file(tests_dir, "test-p", {"args": {"status": 200, "data": {"val": 10}}, "fake": {"reads": ["$.val"], "evaluate": True}})
        create_trace_file(traces_dir, "test-p", obs_status=200)

        # Run with only test-p -> exit code 0
        cmd_pass = [
            "uv", "run", "cairn-test", "run",
            "--tests-dir", str(tests_dir),
            "--traces-dir", str(traces_dir),
            "--id", "test-p",
            "--json"
        ]
        res_pass = subprocess.run(cmd_pass, capture_output=True, text=True)
        assert res_pass.returncode == 0, f"Expected 0, got {res_pass.returncode}. stderr: {res_pass.stderr}"
        data_pass = json.loads(res_pass.stdout)
        assert data_pass["outcome"] == "PASS"
        assert data_pass["summary"]["passed"] == 1

        # 2. FAIL test -> exit code 1
        create_test_file(tests_dir, "test-f", {"args": {"status": 200, "data": {"val": 10}}, "fake": {"reads": ["$.val"], "evaluate": False}})
        cmd_fail = [
            "uv", "run", "cairn-test", "run",
            "--tests-dir", str(tests_dir),
            "--traces-dir", str(traces_dir),
            "--id", "test-f",
            "--json"
        ]
        res_fail = subprocess.run(cmd_fail, capture_output=True, text=True)
        assert res_fail.returncode == 1, f"Expected 1, got {res_fail.returncode}"
        data_fail = json.loads(res_fail.stdout)
        assert data_fail["outcome"] == "FAIL"
        assert data_fail["summary"]["failed"] == 1

        # 3. DRIFT test -> exit code 2
        create_test_file(tests_dir, "test-d", {"args": {"status": 200, "data": {}}, "fake": {"reads": ["$.val"], "evaluate": "missing"}})
        create_trace_file(traces_dir, "test-d", obs_status=200)
        cmd_drift = [
            "uv", "run", "cairn-test", "run",
            "--tests-dir", str(tests_dir),
            "--traces-dir", str(traces_dir),
            "--id", "test-d",
            "--json"
        ]
        res_drift = subprocess.run(cmd_drift, capture_output=True, text=True)
        assert res_drift.returncode == 2, f"Expected 2, got {res_drift.returncode}"
        data_drift = json.loads(res_drift.stdout)
        assert data_drift["outcome"] == "DRIFT"
        assert data_drift["summary"]["drifted"] == 1

        # 4. ERROR test -> exit code 3
        create_test_file(tests_dir, "test-e", {"args": {"transport_error": "Connection refused"}, "fake": {"reads": ["$.status"], "evaluate": "missing"}})
        cmd_error = [
            "uv", "run", "cairn-test", "run",
            "--tests-dir", str(tests_dir),
            "--traces-dir", str(traces_dir),
            "--id", "test-e",
            "--json"
        ]
        res_error = subprocess.run(cmd_error, capture_output=True, text=True)
        assert res_error.returncode == 3, f"Expected 3, got {res_error.returncode}"
        data_error = json.loads(res_error.stdout)
        assert data_error["outcome"] == "ERROR"
        assert data_error["summary"]["errored"] == 1

        print("CLI exit codes, JSON reporting, and text summary tests PASSED!")

if __name__ == "__main__":
    test_cli_exit_codes_and_json()
