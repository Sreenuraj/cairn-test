"""
Test for interactive tutorial command (T8.1).
"""

from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cairn_test.tutorial import run_tutorial

def test_tutorial_non_interactive():
    code = run_tutorial(interactive=False)
    assert code == 0, f"Tutorial failed with exit code {code}"
    print("Interactive tutorial non-interactive test passed successfully.")

if __name__ == "__main__":
    test_tutorial_non_interactive()
