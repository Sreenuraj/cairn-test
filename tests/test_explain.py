"""
Tests for explain command and stored event explanation (T1.11, FR-G2, FR-O7).
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

def test_explain_command():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        tests_dir = base / "tests"
        traces_dir = base / "traces"
        tests_dir.mkdir()
        traces_dir.mkdir()

        # 1. Create a PASS test and a DRIFT test
        create_test_file(tests_dir, "test-p", {"args": {"status": 200, "data": {"val": 10}}, "fake": {"reads": ["$.val"], "evaluate": True}})
        create_trace_file(traces_dir, "test-p", obs_status=200)

        create_test_file(tests_dir, "test-d", {"args": {"status": 200, "data": {}}, "fake": {"reads": ["$.val"], "evaluate": "missing"}})
        create_trace_file(traces_dir, "test-d", obs_status=200)

        # Run suite and get run_id
        cmd_run = [
            "uv", "run", "cairn-test", "run",
            "--tests-dir", str(tests_dir),
            "--traces-dir", str(traces_dir),
            "--json"
        ]
        res_run = subprocess.run(cmd_run, capture_output=True, text=True)
        run_data = json.loads(res_run.stdout)
        run_id = run_data["run_id"]

        # 2. Explain PASS test
        cmd_exp_p = ["uv", "run", "cairn-test", "explain", run_id, "test-p", "--json"]
        res_exp_p = subprocess.run(cmd_exp_p, capture_output=True, text=True)
        assert res_exp_p.returncode == 0
        exp_p = json.loads(res_exp_p.stdout)
        assert exp_p["outcome"] == "PASS"
        assert "executed cleanly" in exp_p["explanation"]

        # 3. Explain DRIFT test
        cmd_exp_d = ["uv", "run", "cairn-test", "explain", run_id, "test-d", "--json"]
        res_exp_d = subprocess.run(cmd_exp_d, capture_output=True, text=True)
        assert res_exp_d.returncode == 0
        exp_d = json.loads(res_exp_d.stdout)
        assert exp_d["outcome"] == "DRIFT"
        assert "drifted" in exp_d["explanation"].lower()
        assert "$.val" in exp_d["drift_detail"]["breaking_paths"]

        print("Explain command and stored event explanation tests PASSED!")

if __name__ == "__main__":
    test_explain_command()
