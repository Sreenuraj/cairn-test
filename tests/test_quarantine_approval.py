"""
Test for T3.7 (FR-C19): Quarantine as an approved edit.

A quarantine tag modifies the test definition content.
In strict mode:
1. If an unapproved edit adds `quarantine`, verification rejects it as `tampered`.
2. Once the edit is signed and approved by the human key, the planner marks it SKIPPED (quarantined).
"""

import os
from pathlib import Path
import subprocess
import tempfile
import yaml

from cairn_test.core.approval import compute_covers, sign_approval, verify_approval
from cairn_test.core.planner import Planner, discover_tests
from cairn_test.core.scheduler import Scheduler
from cairn_test.core.events import EventBus, EventStore
from cairn_test.core.plugins import PluginRegistry
from cairn_test.plugins.fake import register_fake_plugin

def test_quarantine_requires_approved_edit():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "tests").mkdir()
        (root / "traces").mkdir()
        (root / "approvals").mkdir()

        # Generate keypair
        key_path = root / "id_human"
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path), "-C", "human"], check=True, capture_output=True)
        pub_key = (root / "id_human.pub").read_text().strip()
        os.environ["CAIRN_ALLOWED_SIGNERS"] = f"human namespaces=\"cairn-test\" {pub_key}\n"

        test_file = root / "tests" / "flaky.test.yaml"
        test_file.write_text("""schema: cairn-test.test/v1
id: flaky
tags: [smoke]
steps:
  - id: s1
    fake: pass
expect:
  - after: s1
    fake: pass
""")

        trace_file = root / "traces" / "flaky.trace.yaml"
        trace_file.write_text("""schema: cairn-test.trace/v1
test: flaky
env_profile: local
steps:
  - id: s1
    observation: { status: 200 }
""")

        test_def = yaml.safe_load(test_file.read_text())
        covers = compute_covers(root, "flaky", test_def)
        appr_doc = {
            "schema": "cairn-test.approval/v1",
            "subject": "flaky",
            "covers": covers,
            "approver": {"name": "human", "key": "key:human", "key_type": "ssh-ed25519"},
            "at": "2026-11-03T10:00:00Z",
            "labels": ["new-test"],
        }
        sig = sign_approval(appr_doc, key_path=key_path)
        (root / "approvals" / "flaky.approval.yaml").write_text(yaml.safe_dump(appr_doc, sort_keys=False))
        (root / "approvals" / "flaky.approval.yaml.sig").write_text(sig)

        # Baseline: valid
        ok, reason = verify_approval(root, "flaky", active_env="local")
        assert ok is True

        # 1. Unapproved quarantine edit: agent adds `quarantine` tag without human re-approval
        test_file.write_text("""schema: cairn-test.test/v1
id: flaky
tags: [smoke, quarantine]
steps:
  - id: s1
    fake: pass
expect:
  - after: s1
    fake: pass
""")
        ok_tampered, reason_tampered = verify_approval(root, "flaky", active_env="local")
        assert ok_tampered is False
        assert reason_tampered == "tampered", f"Expected tampered, got {reason_tampered}"

        # 2. Approved quarantine edit: human re-signs the approval covering the quarantined test
        test_def_quarantined = yaml.safe_load(test_file.read_text())
        covers_quarantined = compute_covers(root, "flaky", test_def_quarantined)
        appr_doc["covers"] = covers_quarantined
        appr_doc["labels"] = ["quarantined"]
        sig_q = sign_approval(appr_doc, key_path=key_path)
        (root / "approvals" / "flaky.approval.yaml").write_text(yaml.safe_dump(appr_doc, sort_keys=False))
        (root / "approvals" / "flaky.approval.yaml.sig").write_text(sig_q)

        # Now verification succeeds
        ok_approved, _ = verify_approval(root, "flaky", active_env="local")
        assert ok_approved is True

        # Execution in strict mode: planner marks test as SKIPPED (quarantined)
        store = EventStore(base_dir=root / ".cairn-test")
        bus = EventBus("strict-quarantine-run", store=store)
        registry = PluginRegistry()
        register_fake_plugin(registry)
        planner = Planner(event_bus=bus)
        planned = planner.plan_suite([test_def_quarantined])
        assert len(planned) == 1
        assert planned[0].action == "SKIPPED"
        assert planned[0].reason == "quarantined"

        scheduler = Scheduler("strict-q-run", "local", registry, bus, store)
        verdicts = scheduler.run_suite(planned, verification_status={"flaky": "valid"})
        assert len(verdicts) == 1
        assert verdicts[0].outcome == "SKIPPED"
        assert verdicts[0].reason == "quarantined"

if __name__ == "__main__":
    test_quarantine_requires_approved_edit()
    print("All T3.7 quarantine approval tests passed!")
