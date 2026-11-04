"""
Tests for Plugin Developer Kit (PDK) Scaffolder (T8.3).
"""

from pathlib import Path
import subprocess
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cairn_test.core.pdk import scaffold_plugin

def test_pdk_scaffolder() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        target = Path(tmp_dir) / "grpc"
        res = scaffold_plugin("grpc", target)

        assert res["status"] == "created"
        assert res["plugin"] == "grpc"
        assert len(res["files"]) == 8

        # Verify all files exist
        for f in res["files"]:
            assert Path(f).is_file(), f"Missing expected plugin file {f}"

        # Execute the generated test suite
        test_script = target / "test_grpc_plugin.py"
        run_res = subprocess.run(
            [sys.executable, str(test_script)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert run_res.returncode == 0, f"Plugin test failed:\n{run_res.stderr}\n{run_res.stdout}"
        assert "All Grpc Plugin contracts successfully passed!" in run_res.stdout
        print("PDK scaffolder and contract test suite verified successfully.")

if __name__ == "__main__":
    test_pdk_scaffolder()
