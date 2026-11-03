"""
Tests for cryptographic approval and strict mode verification (T3.4, T3.5, FR-R4, FR-R8, FR-V1..FR-V7).
"""

import os
from pathlib import Path
import subprocess
import tempfile
import yaml

from cairn_test.core.approval import (
    canonicalize_approval_payload,
    compute_covers,
    compute_file_sha256,
    normalize_bytes,
    sign_approval,
    verify_approval,
)

def create_test_keypair(dir_path: Path, name: str = "human") -> tuple[Path, str]:
    key_path = dir_path / f"id_{name}"
    cmd = [
        "ssh-keygen",
        "-t", "ed25519",
        "-N", "",
        "-f", str(key_path),
        "-C", f"{name}@cairn-test",
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    pub_key = (dir_path / f"id_{name}.pub").read_text().strip()
    return key_path, pub_key

def test_line_ending_normalization():
    b_crlf = b"line 1\r\nline 2\r\n"
    b_lf = b"line 1\nline 2\n"
    assert normalize_bytes(b_crlf) == b_lf

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        f1 = tmp / "f1.txt"
        f1.write_bytes(b_crlf)
        f2 = tmp / "f2.txt"
        f2.write_bytes(b_lf)
        assert compute_file_sha256(f1) == compute_file_sha256(f2)

def test_canonicalize_payload():
    d1 = {"z": 1, "a": {"y": 2, "b": 3}}
    d2 = {"a": {"b": 3, "y": 2}, "z": 1}
    c1 = canonicalize_approval_payload(d1)
    c2 = canonicalize_approval_payload(d2)
    assert c1 == c2
    assert c1 == b'{"a":{"b":3,"y":2},"z":1}\n'

def test_compute_covers():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "tests").mkdir()
        (root / "traces").mkdir()
        (root / "data").mkdir()
        (root / "plugins").mkdir()

        t_file = root / "tests" / "test-1.test.yaml"
        t_file.write_text("schema: cairn-test.test/v1\nid: test-1\n")

        tr_file = root / "traces" / "test-1.trace.yaml"
        tr_file.write_text("schema: cairn-test.trace/v1\ntest: test-1\n")

        d_file = root / "data" / "customers.yaml"
        d_file.write_text("user: alice\n")

        p_file = root / "plugins" / "custom.py"
        p_file.write_text("def custom(): pass\n")

        cfg_file = root / "cairn-test.yaml"
        cfg_file.write_text("version: '1.0'\n")

        test_def = {
            "schema": "cairn-test.test/v1",
            "id": "test-1",
            "data": {"cust": {"from": "data/customers.yaml#user"}},
        }

        covers = compute_covers(root, "test-1", test_def)
        assert "tests/test-1.test.yaml" in covers
        assert "traces/test-1.trace.yaml" in covers
        assert "data/customers.yaml" in covers
        assert "plugins/custom.py" in covers
        assert "cairn-test.yaml" in covers

def test_signing_and_verification_workflow():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "tests").mkdir()
        (root / "traces").mkdir()
        (root / "approvals").mkdir()

        key_path, pub_key = create_test_keypair(root, "alice")
        os.environ["CAIRN_ALLOWED_SIGNERS"] = f"alice namespaces=\"cairn-test\" {pub_key}\n"

        test_file = root / "tests" / "test-1.test.yaml"
        test_file.write_text("schema: cairn-test.test/v1\nid: test-1\n")
        trace_file = root / "traces" / "test-1.trace.yaml"
        trace_file.write_text("schema: cairn-test.trace/v1\ntest: test-1\nenv_profile: local\n")

        covers = compute_covers(root, "test-1", {"id": "test-1"})
        appr_doc = {
            "schema": "cairn-test.approval/v1",
            "subject": "test-1",
            "covers": covers,
            "approver": {
                "name": "alice",
                "key": "key:alice",
                "key_type": "ssh-ed25519",
            },
            "at": "2026-11-03T10:00:00Z",
            "labels": ["new-test"],
        }

        # Sign
        sig_text = sign_approval(appr_doc, key_path=key_path)
        appr_file = root / "approvals" / "test-1.approval.yaml"
        with open(appr_file, "w") as f:
            yaml.safe_dump(appr_doc, f)
        (root / "approvals" / "test-1.approval.yaml.sig").write_text(sig_text)

        # Verify valid
        valid, reason = verify_approval(root, "test-1", active_env="local")
        assert valid is True
        assert reason is None

        # Verify env mismatch
        valid_env, reason_env = verify_approval(root, "test-1", active_env="staging")
        assert valid_env is False
        assert reason_env == "env-mismatch"

        # Verify tampered
        test_file.write_text("schema: cairn-test.test/v1\nid: test-1\n# tampered\n")
        valid_tamp, reason_tamp = verify_approval(root, "test-1", active_env="local")
        assert valid_tamp is False
        assert reason_tamp == "tampered"

if __name__ == "__main__":
    test_line_ending_normalization()
    test_canonicalize_payload()
    test_compute_covers()
    test_signing_and_verification_workflow()
    print("All T3.4 / T3.5 approval tests passed!")

