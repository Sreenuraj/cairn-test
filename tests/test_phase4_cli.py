"""
End-to-end CLI tests for Phase 4: impact, heal, accept-observations, run --changed, and approval promotion.
"""

from pathlib import Path
import subprocess
import sys
import tempfile
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "cairn_test.cli"] + args
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO_ROOT / "src"), "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )

def test_phase4_cli_e2e():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # 1. Init project
        res_init = run_cli(["init"], cwd=tmp_path)
        assert res_init.returncode == 0, f"Init failed: {res_init.stderr}"

        # 2. Write old spec and new spec
        old_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {
                "/orders": {
                    "post": {
                        "operationId": "createOrder",
                        "parameters": [],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["items"],
                                        "properties": {"items": {"type": "array"}},
                                    }
                                }
                            }
                        },
                    }
                }
            },
        }
        new_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "2.0"},
            "paths": {
                "/v2/orders": {
                    "post": {
                        "operationId": "createOrder",
                        "parameters": [],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["items"],
                                        "properties": {"items": {"type": "array"}},
                                    }
                                }
                            }
                        },
                    }
                }
            },
        }
        old_spec_file = tmp_path / "old_spec.yaml"
        new_spec_file = tmp_path / "new_spec.yaml"
        with open(old_spec_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(old_spec, f)
        with open(new_spec_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(new_spec, f)

        # 3. Create a test and recorded trace
        test_file = tmp_path / "tests" / "create_order.test.yaml"
        test_content = {
            "schema": "cairn-test.test/v1",
            "id": "create_order",
            "steps": [
                {
                    "id": "step_0",
                    "op": "createOrder",
                    "args": {"items": ["item1"]},
                }
            ],
            "expect": [{"status": 201}],
        }
        with open(test_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(test_content, f)

        trace_file = tmp_path / "traces" / "create_order.trace.yaml"
        trace_content = {
            "schema": "cairn-test.trace/v1",
            "test": "create_order",
            "env_profile": "local",
            "spec_hash": "sha256:123456",
            "steps": [
                {
                    "id": "step_0",
                    "step_hash": "sha256:abcdef",
                    "resolved": {
                        "operation": "createOrder",
                        "method": "POST",
                        "path": "/orders",
                    },
                    "pre_fingerprint": {"state": {}},
                    "observation": {
                        "status": 201,
                        "headers": ["content-type"],
                        "body": {"id": "1"},
                    },
                    "recorded_at": "2026-11-03T10:00:00Z",
                }
            ],
        }
        with open(trace_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(trace_content, f)

        # 4. Test impact CLI command
        res_impact = run_cli(["impact", "--spec-diff", "old_spec.yaml", "new_spec.yaml"], cwd=tmp_path)
        assert res_impact.returncode == 0
        assert "AFFECTED create_order" in res_impact.stdout

        res_impact_json = run_cli(["impact", "--spec-diff", "old_spec.yaml", "new_spec.yaml", "--json"], cwd=tmp_path)
        assert res_impact_json.returncode == 0
        assert '"test_id": "create_order"' in res_impact_json.stdout

        # 5. Test heal CLI command
        res_heal = run_cli(["heal", "--spec-diff", "old_spec.yaml", "new_spec.yaml"], cwd=tmp_path)
        assert res_heal.returncode == 0
        assert "HEAL PROPOSAL" in res_heal.stdout
        assert "Generated 1 inert proposals" in res_heal.stdout

        # Verify proposal exists
        prop_trace = tmp_path / "proposals" / "create_order.trace.yaml"
        assert prop_trace.is_file(), "Draft healed trace must exist"
        with open(prop_trace, "r", encoding="utf-8") as f:
            healed_trace_data = yaml.safe_load(f)
        assert healed_trace_data["steps"][0]["resolved"]["path"] == "/v2/orders"

        # 6. Test run --changed with spec diff
        res_run_changed = run_cli(["run", "--changed", "--spec-diff", "old_spec.yaml", "new_spec.yaml"], cwd=tmp_path)
        # Without running target server, step execution produces ERROR (exit code 3)
        assert res_run_changed.returncode in [0, 1, 2, 3]
        assert "create_order" in res_run_changed.stdout

        # 7. Approve healed proposal using an ssh key
        key_path = tmp_path / "id_ed25519"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path)],
            check=True,
            capture_output=True,
        )
        pub_key = (tmp_path / "id_ed25519.pub").read_text().strip()

        # Approve
        res_appr = run_cli(["approve", "create_order", "--key", str(key_path), "--identity", "tester@test.com"], cwd=tmp_path)
        assert res_appr.returncode == 0
        assert "Successfully approved 'create_order'" in res_appr.stdout

        # Verify that the trace in traces/ was promoted with the new path
        with open(trace_file, "r", encoding="utf-8") as f:
            promoted_trace = yaml.safe_load(f)
        assert promoted_trace["steps"][0]["resolved"]["path"] == "/v2/orders"

        # Verify strict mode verifies approval
        env_vars = {"CAIRN_ALLOWED_SIGNERS": f"tester@test.com {pub_key}"}
        cmd_ver = [sys.executable, "-m", "cairn_test.cli", "verify", "create_order"]
        res_ver = subprocess.run(
            cmd_ver,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env={**env_vars, "PYTHONPATH": str(REPO_ROOT / "src"), "PATH": "/usr/bin:/bin:/usr/local/bin"},
        )
        assert res_ver.returncode == 0
        assert "VALID    create_order" in res_ver.stdout

        # 8. Test accept-observations CLI command
        # Simulate draft observation update
        obs_trace = dict(promoted_trace)
        obs_trace["steps"][0]["observation"]["body"]["new_opt"] = "hello"
        with open(tmp_path / "proposals" / "create_order.trace.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(obs_trace, f)

        res_accept = run_cli(["accept-observations"], cwd=tmp_path)
        assert res_accept.returncode == 0
        assert "Created 1 observation acceptance proposals" in res_accept.stdout

        print("Phase 4 CLI E2E tests passed!")

if __name__ == "__main__":
    test_phase4_cli_e2e()
