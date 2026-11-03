"""
End-to-end CLI workflow tests for Phase 3:
init -> write test -> record -> review -> verify -> approve -> run --strict -> tamper check.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bench.service.api import StoreApiHandler, start_reference_server

def test_full_phase3_workflow():
    server, base_url = start_reference_server(0)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)

        # 1. Generate human keypair and set CI trust root
        key_path = root / "id_tester"
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path), "-C", "tester"], check=True, capture_output=True)
        pub_key = (root / "id_tester.pub").read_text().strip()
        os.environ["CAIRN_ALLOWED_SIGNERS"] = f"tester namespaces=\"cairn-test\" {pub_key}\n"

        # 2. cairn-test init
        res_init = subprocess.run(
            ["uv", "run", "cairn-test", "init", "--dir", str(root)],
            capture_output=True, text=True, check=True
        )
        assert "Initialized cairn-test project" in res_init.stdout
        assert (root / "cairn-test.yaml").is_file()
        assert (root / "tests").is_dir()
        assert (root / "proposals").is_dir()

        # Update local env with server base_url
        (root / "envs" / "local.yaml").write_text(f"base_url: '{base_url}'\n")

        # Copy reference spec
        spec_src = Path("bench/service/openapi.yaml").resolve()
        spec_dest = root / "openapi.yaml"
        spec_dest.write_text(spec_src.read_text())

        # 3. Author a new test definition
        test_file = root / "tests" / "get-products.test.yaml"
        test_file.write_text("""schema: cairn-test.test/v1
id: get-products
tags: [products, smoke]
steps:
  - id: list
    op: getProducts
    args: {}
expect:
  - after: list
    status: 200
  - after: list
    jsonpath: $.count
    range: { min: 1, max: 10 }
""")

        # 4. cairn-test record (writes to proposals/)
        res_rec = subprocess.run(
            ["uv", "run", "cairn-test", "record", "--id", "get-products", "--tests-dir", str(root / "tests"), "--traces-dir", str(root / "traces")],
            cwd=str(root),
            capture_output=True, text=True, check=True
        )
        assert "Recorded proposal for 'get-products'" in res_rec.stdout
        proposal_file = root / "proposals" / "get-products.proposal.yaml"
        assert proposal_file.is_file()
        assert not (root / "traces" / "get-products.trace.yaml").is_file()

        # 5. cairn-test review
        res_rev = subprocess.run(
            ["uv", "run", "cairn-test", "review", "--tests-dir", str(root / "tests")],
            cwd=str(root),
            capture_output=True, text=True, check=True
        )
        assert "[PROPOSAL PENDING]" in res_rev.stdout
        assert "new-test" in res_rev.stdout

        # 6. cairn-test verify (fails before approval: unapproved)
        res_ver_pre = subprocess.run(
            ["uv", "run", "cairn-test", "verify", "--tests-dir", str(root / "tests")],
            cwd=str(root),
            capture_output=True, text=True
        )
        assert res_ver_pre.returncode != 0
        assert "INVALID  get-products (reason: unapproved)" in res_ver_pre.stdout

        # 7. cairn-test approve (promotes proposal, signs with OpenSSH)
        res_appr = subprocess.run(
            ["uv", "run", "cairn-test", "approve", "get-products", "--key", str(key_path), "--identity", "tester"],
            cwd=str(root),
            capture_output=True, text=True, check=True
        )
        assert "Successfully approved 'get-products'" in res_appr.stdout
        assert (root / "traces" / "get-products.trace.yaml").is_file()
        assert (root / "approvals" / "get-products.approval.yaml").is_file()
        assert (root / "approvals" / "get-products.approval.yaml.sig").is_file()
        assert not proposal_file.is_file()

        # 8. cairn-test verify (now VALID)
        res_ver_post = subprocess.run(
            ["uv", "run", "cairn-test", "verify", "--tests-dir", str(root / "tests")],
            cwd=str(root),
            capture_output=True, text=True, check=True
        )
        assert "VALID    get-products" in res_ver_post.stdout

        # 9. cairn-test run --strict (succeeds)
        res_run = subprocess.run(
            ["uv", "run", "cairn-test", "run", "--strict", "--tests-dir", str(root / "tests"), "--traces-dir", str(root / "traces")],
            cwd=str(root),
            capture_output=True, text=True, check=True
        )
        assert "PASS    get-products" in res_run.stdout

        # 10. Tamper check: agent edits expectation
        orig_test_content = test_file.read_text()
        test_file.write_text(orig_test_content.replace("status: 200", "status: 201"))
        res_run_tampered = subprocess.run(
            ["uv", "run", "cairn-test", "run", "--strict", "--tests-dir", str(root / "tests"), "--traces-dir", str(root / "traces")],
            cwd=str(root),
            capture_output=True, text=True
        )
        assert res_run_tampered.returncode != 0
        assert "ERROR   get-products - tampered" in res_run_tampered.stdout

if __name__ == "__main__":
    test_full_phase3_workflow()
    print("All Phase 3 end-to-end CLI workflow tests passed!")
