"""
Project scaffolding engine for cairn-test init (T3.1, FR-R1).

Initializes standard project layout:
  cairn-test.yaml
  tests/
  traces/
  approvals/
  proposals/
  reports/
  data/
  envs/
"""

from __future__ import annotations
from pathlib import Path
import shutil
from typing import Any
import yaml

DEFAULT_CONFIG_CONTENT = """# cairn-test project configuration
version: "1.0"
spec: "{spec_path}"
default_env: "local"

envs:
  local: "envs/local.yaml"
  staging: "envs/staging.yaml"

masking:
  secret_names:
    - "authorization"
    - "api_key"
    - "token"
    - "password"
    - "secret"
  pii_fields:
    - "$.email"
    - "$.user.email"
    - "$.customer.email"
"""

DEFAULT_LOCAL_ENV = """# Local environment configuration
base_url: "http://127.0.0.1:8000"
timeout_ms: 5000
"""

DEFAULT_STAGING_ENV = """# Staging environment configuration
base_url: "https://staging.example.com"
timeout_ms: 10000
"""

DEFAULT_DATA_CUSTOMER = """# Reusable customer test data
guest:
  user: "guest_user"
  password: "guest_password_123"

alice:
  user: "alice"
  password: "password123"
"""

def init_project(target_dir: Path, spec_path: str | None = None) -> dict[str, Any]:
    """Scaffold standard cairn-test project directory layout."""
    target_dir = Path(target_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    # Required directories
    dirs = [
        target_dir / "tests",
        target_dir / "traces",
        target_dir / "approvals",
        target_dir / "proposals",
        target_dir / "reports",
        target_dir / "data",
        target_dir / "envs",
        target_dir / "plugins",
        target_dir / ".cairn-test",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # Handle spec file
    final_spec_path = "openapi.yaml"
    if spec_path:
        src_spec = Path(spec_path).expanduser().resolve()
        if src_spec.is_file():
            dest_spec = target_dir / src_spec.name
            if src_spec != dest_spec:
                shutil.copy2(src_spec, dest_spec)
            final_spec_path = src_spec.name
        else:
            final_spec_path = str(spec_path)

    # Write cairn-test.yaml
    cfg_file = target_dir / "cairn-test.yaml"
    if not cfg_file.exists():
        cfg_file.write_text(DEFAULT_CONFIG_CONTENT.format(spec_path=final_spec_path), encoding="utf-8")

    # Write default env files
    local_env = target_dir / "envs" / "local.yaml"
    if not local_env.exists():
        local_env.write_text(DEFAULT_LOCAL_ENV, encoding="utf-8")

    staging_env = target_dir / "envs" / "staging.yaml"
    if not staging_env.exists():
        staging_env.write_text(DEFAULT_STAGING_ENV, encoding="utf-8")

    # Write default data file
    cust_data = target_dir / "data" / "customers.yaml"
    if not cust_data.exists():
        cust_data.write_text(DEFAULT_DATA_CUSTOMER, encoding="utf-8")

    return {
        "status": "initialized",
        "root": str(target_dir),
        "spec": final_spec_path,
        "directories": [str(d.relative_to(target_dir)) for d in dirs],
    }

