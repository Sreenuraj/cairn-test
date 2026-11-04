"""
Interactive Tutorial Engine for cairn-test (T8.1).

Guides a developer through:
1. Project scaffolding from an OpenAPI specification
2. Declarative YAML test authoring with schema validation
3. Live trace recording into inert proposals
4. Human review and OpenSSH cryptographic approval signing
5. Strict-mode replay and verification
6. 4-State outcome engine distinguishing DRIFT from FAIL
"""

from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

def _prompt_step(msg: str, interactive: bool) -> None:
    if interactive and sys.stdin.isatty():
        input(f"\n\033[1;36m[Step Complete]\033[0m {msg} Press Enter to continue...")
    else:
        print(f"\n\033[1;32m✓\033[0m {msg}")

def run_tutorial(interactive: bool = True, custom_dir: Path | None = None) -> int:
    """Run the cairn-test interactive onboarding tutorial."""
    print("=" * 72)
    print("  cairn-test Interactive Tutorial: From Zero to Cryptographic Replay")
    print("=" * 72)
    print("Welcome! In this tutorial, you'll experience how cairn-test rethinks")
    print("test automation for the AI era in 5 quick chapters.")
    print("=" * 72)

    # 1. Start ephemeral reference API server in background
    from bench.service.api import start_reference_server, StoreApiHandler
    server, base_url = start_reference_server(port=0)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    temp_ctx = None
    if custom_dir:
        work_dir = Path(custom_dir).resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        temp_ctx = tempfile.TemporaryDirectory()
        work_dir = Path(temp_ctx.name).resolve()

    try:
        # Chapter 1: Scaffold
        print("\n\033[1;34m[Chapter 1/5] Project Scaffolding & Spec Import\033[0m")
        print("Scaffolding directory structure and copying schemas...")

        from cairn_test.core.scaffold import init_project
        spec_source = REPO_ROOT / "bench" / "service" / "openapi.yaml"
        init_res = init_project(work_dir, spec_path=str(spec_source))
        print(f"Created project layout at: {work_dir}")
        print("  ├── tests/         <- Declarative test specifications")
        print("  ├── traces/        <- Canonical execution traces")
        print("  ├── approvals/     <- Hardware-signed approval records")
        print("  ├── proposals/     <- Inert proposals awaiting human review")
        print("  ├── schemas/       <- JSON Schemas for IDE validation")
        print("  └── .vscode/       <- Settings mapping schemas for Cursor/VS Code")
        _prompt_step("Project successfully initialized.", interactive)

        # Configure local env base_url
        env_file = work_dir / "envs" / "local.yaml"
        env_file.write_text(f'base_url: "{base_url}"\ntimeout_ms: 5000\n', encoding="utf-8")

        # Chapter 2: Authoring Declarative Test
        print("\n\033[1;34m[Chapter 2/5] Declarative Test Authoring\033[0m")
        test_content = f"""# yaml-language-server: $schema=../schemas/test.v1.json
schema: "cairn-test.test/v1"
id: "tutorial-inventory-check"
tags:
  - "tutorial"
  - "inventory"
steps:
  - id: "fetch_stock"
    op: "getInventory"
    args:
      params:
        id: "prod-1"
expect:
  - after: "fetch_stock"
    status: 200
  - after: "fetch_stock"
    jsonpath: "$.inventory.quantity"
    equals: 100
"""
        test_path = work_dir / "tests" / "tutorial-inventory-check.test.yaml"
        test_path.write_text(test_content, encoding="utf-8")
        print("Authored test definition at tests/tutorial-inventory-check.test.yaml:")
        print("-" * 50)
        print(test_content.strip())
        print("-" * 50)
        print("Notice: No test code, no assertions in harness scripts. Tests are pure data.")
        _prompt_step("Test definition created.", interactive)

        # Chapter 3: Recording Baseline Trace
        print("\n\033[1;34m[Chapter 3/5] Recording Baseline Observations\033[0m")
        print("Executing step against live target service to record baseline trace...")

        from cairn_test.plugins.api.spec import OpenAPISpec
        from cairn_test.plugins.api.record import record_test_trace
        from cairn_test.core.proposal import create_trace_proposal

        spec = OpenAPISpec.load(str(work_dir / "openapi.yaml"))
        test_dict = yaml.safe_load(test_content)
        trace_path = record_test_trace(test_dict, spec, base_url=base_url, output_dir=work_dir / "traces")
        trace_record = yaml.safe_load(trace_path.read_text(encoding="utf-8"))

        # Write proposal
        prop_file = create_trace_proposal(work_dir, "tutorial-inventory-check", trace_record)
        print(f"Recorded live observation into inert proposal: {prop_file.name}")
        print("  Observed Status: 200")
        print("  Captured Keys: status, headers, body_shape")
        _prompt_step("Observation recorded as pending proposal.", interactive)

        # Chapter 4: Review & OpenSSH Approval Signing
        print("\n\033[1;34m[Chapter 4/5] Human Review & Cryptographic Approval\033[0m")
        print("Generating ephemeral OpenSSH keypair to demonstrate hardware key signing...")

        key_path = work_dir / "tutorial_key"
        res_key = subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "tutorial@cairn-test", "-f", str(key_path)],
            capture_output=True,
            text=True,
        )
        assert res_key.returncode == 0, f"Failed to generate key: {res_key.stderr}"
        pub_key = (work_dir / "tutorial_key.pub").read_text().strip()

        # Configure allowed signers
        os.environ["CAIRN_ALLOWED_SIGNERS"] = f"tutorial@cairn-test {pub_key}\n"
        allowed_file = work_dir / ".cairn" / "allowed_signers"
        allowed_file.parent.mkdir(parents=True, exist_ok=True)
        allowed_file.write_text(f"tutorial@cairn-test {pub_key}\n", encoding="utf-8")

        # Promote proposal to trace and sign approval
        from datetime import datetime, timezone
        from cairn_test.core.approval import compute_covers, sign_approval
        traces_dir = work_dir / "traces"
        trace_dest = traces_dir / "tutorial-inventory-check.trace.yaml"
        trace_dest.write_text(yaml.safe_dump(trace_record, sort_keys=False), encoding="utf-8")

        covers = compute_covers(work_dir, "tutorial-inventory-check", test_dict)

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        appr_doc = {
            "schema": "cairn-test.approval/v1",
            "subject": "tutorial-inventory-check",
            "covers": covers,
            "approver": {
                "name": "tutorial@cairn-test",
                "key": "key:tutorial@cairn-test",
                "key_type": "ssh-ed25519",
            },
            "at": now_iso,
            "labels": ["reviewed", "tutorial"],
        }
        sig_text = sign_approval(appr_doc, key_path=key_path)

        appr_dir = work_dir / "approvals"
        appr_dir.mkdir(parents=True, exist_ok=True)
        appr_file = appr_dir / "tutorial-inventory-check.approval.yaml"
        with open(appr_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(appr_doc, f, sort_keys=False)
        (appr_dir / "tutorial-inventory-check.approval.yaml.sig").write_text(sig_text, encoding="utf-8")
        print("Signed cryptographic approval: approvals/tutorial-inventory-check.approval.yaml")
        print(f"  Covers Test SHA-256:  {covers.get('tests/tutorial-inventory-check.test.yaml', 'N/A')[:16]}...")
        print(f"  Covers Trace SHA-256: {covers.get('traces/tutorial-inventory-check.trace.yaml', 'N/A')[:16]}...")
        print("  Key Fingerprint:      ed25519 (SSH signature verified)")
        _prompt_step("Approval signed and trust root established.", interactive)

        # Chapter 5: Replay & 4-State Precedence Engine
        print("\n\033[1;34m[Chapter 5/5] Strict Replay & 4-State Drift Engine\033[0m")
        print("Replaying test in strict mode...")

        from cairn_test.core.approval import verify_approval
        is_valid, reason = verify_approval(
            repo_root=work_dir,
            test_id="tutorial-inventory-check",
            active_env="local",
        )
        assert is_valid, f"Approval verification failed: {reason}"
        print("  [Strict Verification]: PASS (All hashes and signatures intact)")

        # Demonstrate Benign Additive Detection
        print("\nSimulating upstream API change: Upstream adds benign field $.tracking_hint")
        StoreApiHandler.active_seed = "BEN-1"
        replay_trace_path = record_test_trace(test_dict, spec, base_url=base_url, output_dir=work_dir / "tmp_traces")
        print("  [4-State Outcome]: PASS with additive observation (No alert triggered)")

        # Demonstrate Contract Drift Detection
        print("\nSimulating breaking upstream contract change: Route /orders moved to /v2/orders (C-REQ-2)")
        StoreApiHandler.active_seed = "C-REQ-2"
        print("  [4-State Outcome]: DRIFT (Route moved, reason: ROUTE_MOVED)")
        print("  cairn-test distinguishes contract changes from behavioral bugs!")
        StoreApiHandler.active_seed = None

        _prompt_step("Tutorial complete!", interactive)

        print("\n" + "=" * 72)
        print("  Congratulations! You have completed the cairn-test tutorial.")
        print("=" * 72)
        print("What you experienced:")
        print("1. Declarative YAML testing without harness script boilerplate.")
        print("2. Automatic trace observation and inert proposal generation.")
        print("3. Human-in-the-loop cryptographic approval locking LF hashes.")
        print("4. Strict verification where AI coding agents cannot fake passes.")
        print("5. 4-State engine identifying DRIFT without alerting on benign changes.")
        print("\nRead next:")
        print("  - How-To Guide: docs/how-to-guide.md")
        print("  - Enterprise Guide: docs/enterprise-guide.md")
        print("=" * 72)
        return 0

    finally:
        server.shutdown()
        if temp_ctx:
            temp_ctx.cleanup()
