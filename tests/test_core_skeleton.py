"""
Import and boundary tests for cairn-test core (T1.1, NFR-8).
Verifies:
1. Core has zero dependencies on HTTP, browser, or AI model libraries.
2. Configuration loading and defaults.
3. Structured logging.
"""

import importlib
import pkgutil
import subprocess
import sys
import tempfile
from pathlib import Path
import yaml
from cairn_test.config import Config
from cairn_test.logging import setup_logging, get_logger

FORBIDDEN_MODULE_PREFIXES = (
    # HTTP libraries
    "requests",
    "httpx",
    "urllib3",
    "aiohttp",
    "http.client",
    # Browser automation libraries
    "playwright",
    "selenium",
    "puppeteer",
    # AI / Model libraries
    "openai",
    "anthropic",
    "google.genai",
    "google.generativeai",
    "transformers",
    "torch",
    "langchain",
)

def test_nfr8_core_import_isolation():
    """
    NFR-8: Core has no dependency on HTTP, browser, or model libraries (enforced by an import test).
    Runs in a clean subprocess so test runner harness/plugins (e.g. pytest-playwright) do not pollute sys.modules.
    """
    code = """
import sys, pkgutil, importlib
import cairn_test.core

prefix = cairn_test.core.__name__ + "."
for _, modname, _ in pkgutil.walk_packages(cairn_test.core.__path__, prefix):
    importlib.import_module(modname)

FORBIDDEN = (
    "requests", "httpx", "urllib3", "aiohttp", "http.client",
    "playwright", "selenium", "puppeteer",
    "openai", "anthropic", "google.genai", "google.generativeai",
    "transformers", "torch", "langchain",
)
loaded_forbidden = [
    name for name in sys.modules
    if any(name == f or name.startswith(f + ".") for f in FORBIDDEN)
]
if loaded_forbidden:
    print(f"FORBIDDEN:{loaded_forbidden}")
    sys.exit(1)
"""
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, f"NFR-8 VIOLATION: Forbidden modules found in sys.modules: {res.stdout} {res.stderr}"
    print("NFR-8 Check PASSED: No HTTP, browser, or model libraries loaded in core.")

def test_config_loading():
    """Verify config loading and defaults."""
    cfg = Config()
    assert cfg.default_env == "local"
    assert cfg.parallelism == 4
    assert "authorization" in cfg.masking_names

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.dump({
            "spec": "custom_api.yaml",
            "parallelism": 8,
            "default_env": "staging",
            "masking": {"names": ["api_key"], "patterns": ["pattern1"]}
        }, f)
        temp_path = f.name

    try:
        loaded = Config.load(temp_path)
        assert loaded.spec == "custom_api.yaml"
        assert loaded.parallelism == 8
        assert loaded.default_env == "staging"
        assert loaded.masking_names == ["api_key"]
        assert loaded.masking_patterns == ["pattern1"]
        print("Config loading test PASSED.")
    finally:
        Path(temp_path).unlink(missing_ok=True)

def test_logging_setup():
    """Verify logging setup and JSON formatter."""
    setup_logging(json_mode=True)
    logger = get_logger("test")
    assert logger.name == "cairn_test.test"
    setup_logging(json_mode=False)
    print("Logging setup test PASSED.")

if __name__ == "__main__":
    test_nfr8_core_import_isolation()
    test_config_loading()
    test_logging_setup()
    print("All T1.1 skeleton tests passed!")
