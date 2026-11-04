"""
Tests for draft-to-test promotion workflow and positional record command.
"""

from pathlib import Path
import subprocess
import sys
import tempfile
import threading

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bench.service.api import start_reference_server

def test_draft_promotion_and_record_flow():
    server, base_url = start_reference_server(port=0)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    cairn_cmd = [sys.executable, "-m", "cairn_test.cli"]
    cairn_env = {
        "PYTHONPATH": f"{REPO_ROOT}/src:{REPO_ROOT}",
    }

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)

            # 1. cairn-test init with openapi spec
            spec_src = REPO_ROOT / "bench" / "service" / "openapi.yaml"
            res_init = subprocess.run(
                cairn_cmd + ["init", "--dir", str(work_dir), "--spec", str(spec_src)],
                capture_output=True, text=True, cwd=str(work_dir), env=cairn_env, check=True
            )
            assert (work_dir / "README.md").is_file()
            assert (work_dir / "tests" / "sample.test.yaml.example").is_file()

            # Configure local env base_url
            (work_dir / "envs" / "local.yaml").write_text(f'base_url: "{base_url}"\ntimeout_ms: 5000\n')

            # 2. cairn-test draft
            res_draft = subprocess.run(
                cairn_cmd + ["draft", "--spec", "openapi.yaml"],
                capture_output=True, text=True, cwd=str(work_dir), env=cairn_env, check=True
            )
            assert "generated" in res_draft.stdout
            proposals = list((work_dir / "proposals").glob("*.proposal.yaml"))
            assert len(proposals) > 0, "Draft should have created proposals"

            # 3. cairn-test review --json (MUST return draft proposals even when tests/ is empty!)
            res_review = subprocess.run(
                cairn_cmd + ["review", "--json"],
                capture_output=True, text=True, cwd=str(work_dir), env=cairn_env, check=True
            )
            import json
            review_items = json.loads(res_review.stdout)
            assert len(review_items) == len(proposals), f"Review should return all {len(proposals)} proposals"
            assert all(item.get("has_proposal") for item in review_items)

            # 4. cairn-test status before promote -> 0 tests
            res_status_pre = subprocess.run(
                cairn_cmd + ["status", "--json"],
                capture_output=True, text=True, cwd=str(work_dir), env=cairn_env, check=True
            )
            status_data_pre = json.loads(res_status_pre.stdout)
            assert status_data_pre["total_tests"] == 0

            # 5. cairn-test draft --promote
            res_promote = subprocess.run(
                cairn_cmd + ["draft", "--promote"],
                capture_output=True, text=True, cwd=str(work_dir), env=cairn_env, check=True
            )
            assert "promoted" in res_promote.stdout
            test_files = list((work_dir / "tests").glob("*.test.yaml"))
            assert len(test_files) == len(proposals), "All draft proposals should be promoted to tests/"

            # 6. cairn-test status after promote -> >0 tests
            res_status_post = subprocess.run(
                cairn_cmd + ["status", "--json"],
                capture_output=True, text=True, cwd=str(work_dir), env=cairn_env, check=True
            )
            status_data_post = json.loads(res_status_post.stdout)
            assert status_data_post["total_tests"] == len(test_files)

            # 7. Positional record command: cairn-test record tests/sample.test.yaml
            res_rec_sample = subprocess.run(
                cairn_cmd + ["record", "tests/sample.test.yaml", "--base-url", base_url],
                capture_output=True, text=True, cwd=str(work_dir), env=cairn_env, check=True
            )
            assert "Recorded proposal" in res_rec_sample.stdout
            assert (work_dir / "tests" / "sample.test.yaml").is_file()

            # 8. Positional record command on one of the drafted tests:
            first_test_file = test_files[0]
            res_rec_drafted = subprocess.run(
                cairn_cmd + ["record", str(first_test_file), "--base-url", base_url],
                capture_output=True, text=True, cwd=str(work_dir), env=cairn_env, check=True
            )
            assert "Recorded proposal" in res_rec_drafted.stdout

            print("Draft-to-test promotion workflow and positional record verified successfully!")
    finally:
        server.shutdown()

if __name__ == "__main__":
    test_draft_promotion_and_record_flow()
