"""
Test for scaffold README generation and remote spec downloading (FR-R1).
"""

from pathlib import Path
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cairn_test.core.scaffold import init_project

def test_scaffold_readme_and_agent_instructions():
    with tempfile.TemporaryDirectory() as tmp_dir:
        target = Path(tmp_dir) / "sample_service"
        res = init_project(target, spec_path="my_api.yaml")

        readme = target / "README.md"
        assert readme.is_file(), "README.md was not generated in scaffolded project"
        content = readme.read_text(encoding="utf-8")

        # Verify Human Quickstart sections
        assert "Quickstart for Humans" in content
        assert "cairn-test draft --spec my_api.yaml" in content
        assert "Review & Promote Proposals into Tests" in content
        assert "cairn-test draft --promote" in content
        assert "cairn-test record" in content
        assert "cairn-test approve" in content

        # Verify AI Agent Instructions sections
        assert "Instructions for AI Coding Agents" in content
        assert "Tests are Pure Declarative Data" in content
        assert "The Untrusted Agent Invariant" in content
        assert "sign approvals" in content
        assert "yaml-language-server: $schema=../schemas/test.v1.json" in content
        assert "cairn-test impact --spec-diff my_api.yaml" in content

        print("Scaffold README with human and AI agent instructions verified successfully.")

def test_init_remote_spec_download():
    from http.server import HTTPServer, SimpleHTTPRequestHandler
    import threading
    import subprocess

    spec_content = (REPO_ROOT / "bench" / "service" / "openapi.yaml").read_bytes()

    class SpecHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/yaml")
            self.end_headers()
            self.wfile.write(spec_content)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), SpecHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            url = f"http://127.0.0.1:{port}/remote_spec.yaml"
            cmd = [sys.executable, "-m", "cairn_test.cli", "init", "--dir", tmp_dir, "--spec", url]
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
            assert res.returncode == 0, f"Init failed: {res.stderr}\n{res.stdout}"

            dest_spec = Path(tmp_dir) / "remote_spec.yaml"
            assert dest_spec.is_file(), "Remote spec was not downloaded to destination"
            assert dest_spec.read_bytes() == spec_content

            # Verify envs/local.yaml was automatically populated with derived URL
            local_env = (Path(tmp_dir) / "envs" / "local.yaml").read_text(encoding="utf-8")
            assert f"http://127.0.0.1:{port}" in local_env, f"Expected server URL in local.yaml: {local_env}"

            # Verify NO harmful dummy customer data was generated
            assert not (Path(tmp_dir) / "data" / "customers.yaml").exists()

            print("Remote OpenAPI spec download and env derivation in cairn-test init verified successfully.")
    finally:
        server.shutdown()

if __name__ == "__main__":
    test_scaffold_readme_and_agent_instructions()
    test_init_remote_spec_download()
