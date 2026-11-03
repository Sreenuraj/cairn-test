"""
Tamper suite testing every security and integrity case in FR-V5 (T3.6).
"""

import os
from pathlib import Path
import subprocess
import tempfile
import yaml

from cairn_test.core.approval import (
    compute_covers,
    sign_approval,
    verify_approval,
)

def setup_base_approved_test(root: Path) -> tuple[Path, str]:
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "traces").mkdir(parents=True, exist_ok=True)
    (root / "approvals").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "plugins").mkdir(parents=True, exist_ok=True)

    # Keypair
    key_path = root / "id_human"
    subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path), "-C", "human"], check=True, capture_output=True)
    pub_key = (root / "id_human.pub").read_text().strip()

    os.environ["CAIRN_ALLOWED_SIGNERS"] = f"human namespaces=\"cairn-test\" {pub_key}\n"

    # Files
    cfg = root / "cairn-test.yaml"
    cfg.write_text("version: '1.0'\n")

    t_file = root / "tests" / "auth-test.test.yaml"
    t_file.write_text("""schema: cairn-test.test/v1
id: auth-test
data:
  user: { from: data/users.yaml#alice }
steps:
  - id: s1
    op: login
    args: { user: "{user}" }
expect:
  - after: s1
    status: 200
""")

    tr_file = root / "traces" / "auth-test.trace.yaml"
    tr_file.write_text("""schema: cairn-test.trace/v1
test: auth-test
env_profile: local
steps:
  - id: s1
    observation:
      status: 200
      body_shape: { token: string }
""")

    d_file = root / "data" / "users.yaml"
    d_file.write_text("alice: { name: alice }\n")

    p_file = root / "plugins" / "rule.py"
    p_file.write_text("def rule(): return True\n")

    test_def = yaml.safe_load(t_file.read_text())
    covers = compute_covers(root, "auth-test", test_def)

    appr_doc = {
        "schema": "cairn-test.approval/v1",
        "subject": "auth-test",
        "covers": covers,
        "approver": {
            "name": "human",
            "key": "key:human",
            "key_type": "ssh-ed25519",
        },
        "at": "2026-11-03T10:00:00Z",
        "labels": ["new-test"],
    }

    sig_text = sign_approval(appr_doc, key_path=key_path)
    (root / "approvals" / "auth-test.approval.yaml").write_text(yaml.safe_dump(appr_doc, sort_keys=False))
    (root / "approvals" / "auth-test.approval.yaml.sig").write_text(sig_text)

    return key_path, pub_key

def test_fr_v5_all_tamper_cases():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        key_path, pub_key = setup_base_approved_test(root)

        # Baseline: must be valid
        ok, reason = verify_approval(root, "auth-test", active_env="local")
        assert ok is True, f"Baseline verification failed: {reason}"

        # Case 1: Agent modifies test step in tests/<id>.test.yaml
        t_file = root / "tests" / "auth-test.test.yaml"
        orig_t = t_file.read_text()
        t_file.write_text(orig_t.replace("op: login", "op: admin_login"))
        ok, reason = verify_approval(root, "auth-test", active_env="local")
        assert ok is False and reason == "tampered", f"Case 1 failed: {reason}"
        t_file.write_text(orig_t)

        # Case 2: Agent weakens expectation in tests/<id>.test.yaml
        t_file.write_text(orig_t.replace("status: 200", "status: 204"))
        ok, reason = verify_approval(root, "auth-test", active_env="local")
        assert ok is False and reason == "tampered", f"Case 2 failed: {reason}"
        t_file.write_text(orig_t)

        # Case 3: Agent alters recorded observation in traces/<id>.trace.yaml
        tr_file = root / "traces" / "auth-test.trace.yaml"
        orig_tr = tr_file.read_text()
        tr_file.write_text(orig_tr.replace("status: 200", "status: 201"))
        ok, reason = verify_approval(root, "auth-test", active_env="local")
        assert ok is False and reason == "tampered", f"Case 3 failed: {reason}"
        tr_file.write_text(orig_tr)

        # Case 4: Agent modifies data file data/*.yaml
        d_file = root / "data" / "users.yaml"
        orig_d = d_file.read_text()
        d_file.write_text("alice: { name: bob }\n")
        ok, reason = verify_approval(root, "auth-test", active_env="local")
        assert ok is False and reason == "tampered", f"Case 4 failed: {reason}"
        d_file.write_text(orig_d)

        # Case 5: Agent modifies configuration cairn-test.yaml
        cfg_file = root / "cairn-test.yaml"
        orig_cfg = cfg_file.read_text()
        cfg_file.write_text("version: '1.0'\ntampered: true\n")
        ok, reason = verify_approval(root, "auth-test", active_env="local")
        assert ok is False and reason == "tampered", f"Case 5 failed: {reason}"
        cfg_file.write_text(orig_cfg)

        # Case 6: Agent modifies project-local plugin in plugins/
        p_file = root / "plugins" / "rule.py"
        orig_p = p_file.read_text()
        p_file.write_text("def rule(): return False\n")
        ok, reason = verify_approval(root, "auth-test", active_env="local")
        assert ok is False and reason == "tampered", f"Case 6 failed: {reason}"
        p_file.write_text(orig_p)

        # Case 7: Agent modifies approval record without re-signing
        appr_file = root / "approvals" / "auth-test.approval.yaml"
        orig_appr = appr_file.read_text()
        appr_file.write_text(orig_appr.replace("new-test", "malicious-label"))
        ok, reason = verify_approval(root, "auth-test", active_env="local")
        assert ok is False and reason == "bad-signature", f"Case 7 failed: {reason}"
        appr_file.write_text(orig_appr)

        # Case 8: Agent signs with an untrusted key
        agent_key = root / "id_agent"
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(agent_key), "-C", "agent"], check=True, capture_output=True)
        appr_data = yaml.safe_load(orig_appr)
        agent_sig = sign_approval(appr_data, key_path=agent_key)
        (root / "approvals" / "auth-test.approval.yaml.sig").write_text(agent_sig)
        ok, reason = verify_approval(root, "auth-test", active_env="local")
        assert ok is False and reason == "unknown-signer", f"Case 8 failed: {reason}"

        # Re-sign with human key
        human_sig = sign_approval(appr_data, key_path=key_path)
        (root / "approvals" / "auth-test.approval.yaml.sig").write_text(human_sig)

        # Case 9: Agent runs in strict mode without any approval
        ok, reason = verify_approval(root, "nonexistent-test", active_env="local")
        assert ok is False and reason == "unapproved", f"Case 9 failed: {reason}"

        # Case 10: Agent runs in strict mode without a trace
        tr_file.unlink()
        ok, reason = verify_approval(root, "auth-test", active_env="local")
        assert ok is False and reason == "missing-trace", f"Case 10 failed: {reason}"
        tr_file.write_text(orig_tr)

        # Case 11: Agent runs in strict mode with environment mismatch
        ok, reason = verify_approval(root, "auth-test", active_env="staging")
        assert ok is False and reason == "env-mismatch", f"Case 11 failed: {reason}"

if __name__ == "__main__":
    test_fr_v5_all_tamper_cases()
    print("All FR-V5 tamper suite tests passed!")
