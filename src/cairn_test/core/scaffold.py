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
import json
from pathlib import Path
import shutil
from typing import Any
import yaml

from cairn_test.core.schemas import get_schemas_dir

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

DEFAULT_SAMPLE_TEST = """# yaml-language-server: $schema=../schemas/test.v1.json
schema: "cairn-test.test/v1"
id: "sample-health-check"
tags:
  - "smoke"
steps:
  - id: "check"
    op: "getHealth"
    args: {}
expect:
  - after: "check"
    status: 200
"""

DEFAULT_SCAFFOLD_README = """# {project_name} Test Suite

This test suite is powered by [cairn-test](https://github.com/Sreenuraj/cairn-test), a trace-based, domain-neutral test framework for the AI era.

## 🚀 Quickstart for Humans

### 1. Configure Target Service
Update your target endpoint in `envs/local.yaml`:
```yaml
base_url: "http://localhost:8000"  # or your remote staging URL
timeout_ms: 5000
```

### 2. Draft Tests from Specification
Draft baseline test proposals automatically from your OpenAPI contract:
```bash
cairn-test draft --spec {spec_path}
```

### 3. Record Baseline Observations
Record live API responses as inert proposals:
```bash
cairn-test record tests/sample.test.yaml
```

### 4. Review & Sign Cryptographic Approval
```bash
# Inspect proposed changes
cairn-test review

# Sign approval with your SSH hardware key (locks LF SHA-256 hashes)
cairn-test approve <test-id>
```

### 5. Run the Suite
```bash
# Standard dev run
cairn-test run

# Strict verification mode (enforces cryptographic signatures)
cairn-test run --strict
```

---

## 🤖 Instructions for AI Coding Agents (Cursor, Antigravity, Claude, Copilot)

If you are an AI coding assistant working in this repository, follow these rules:

### 1. Tests are Pure Declarative Data
- Write test definitions in `tests/<test-id>.test.yaml`.
- Do not write executable test harnesses or test scripts. Tests must be valid `cairn-test.test/v1` documents.
- Add the schema pragma at the top of every test file:
  ```yaml
  # yaml-language-server: $schema=../schemas/test.v1.json
  schema: "cairn-test.test/v1"
  id: "<test-id>"
  tags:
    - "api"
  steps:
    - id: "step_0"
      op: "<operationId>"
      args: {{}}
  expect:
    - after: "step_0"
      status: 200
  ```

### 2. The Untrusted Agent Invariant
- As an AI agent, you **CANNOT** sign approvals (`cairn-test approve`). You do not possess the human's hardware private key (`ed25519-sk`).
- When you generate or update a test, execute:
  ```bash
  cairn-test record tests/<test-id>.test.yaml
  ```
- Then, inform the human developer:
  > *"I have recorded a new trace proposal for `<test-id>`. Please run `cairn-test review` and `cairn-test approve <test-id>` with your SSH key."*
- **Never attempt to edit assertions or approved trace hashes** to force a failing test to pass.

### 3. Handling Contract Drift & Spec Changes
- When an API route, parameter, or schema changes in `{spec_path}`, run:
  ```bash
  cairn-test impact --spec-diff {spec_path}
  cairn-test heal --spec-diff {spec_path}
  ```
- The healer will generate deterministic proposals for updated request coordinates. Present them to the human for approval.

### 4. Verification Check
- Before finishing your task, verify with:
  ```bash
  cairn-test run
  ```
"""

VSCODE_SETTINGS = {
    "yaml.schemas": {
        "./schemas/test.v1.json": ["tests/**/*.test.yaml", "tests/*.test.yaml"],
        "./schemas/trace.v1.json": ["traces/**/*.trace.yaml", "traces/*.trace.yaml"],
        "./schemas/approval.v1.json": ["approvals/**/*.approval.yaml", "approvals/*.approval.yaml"],
        "./schemas/proposal.v1.json": ["proposals/**/*.proposal.yaml", "proposals/*.proposal.yaml"],
    }
}

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
        target_dir / "schemas",
        target_dir / ".vscode",
        target_dir / ".cairn-test",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # Copy schemas if available
    try:
        src_schemas = get_schemas_dir()
        if src_schemas.is_dir() and src_schemas != target_dir / "schemas":
            shutil.copytree(src_schemas, target_dir / "schemas", dirs_exist_ok=True)
    except Exception:
        pass

    # Write .vscode/settings.json
    vscode_settings_file = target_dir / ".vscode" / "settings.json"
    if not vscode_settings_file.exists():
        vscode_settings_file.write_text(json.dumps(VSCODE_SETTINGS, indent=2) + "\n", encoding="utf-8")

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

    # Write default sample test template with schema pragma
    sample_test = target_dir / "tests" / "sample.test.yaml.example"
    if not sample_test.exists():
        sample_test.write_text(DEFAULT_SAMPLE_TEST, encoding="utf-8")

    # Write scaffold README with human quickstart & AI agent instructions
    readme_file = target_dir / "README.md"
    readme_content = DEFAULT_SCAFFOLD_README.format(project_name=target_dir.name, spec_path=final_spec_path)
    if not readme_file.exists():
        readme_file.write_text(readme_content, encoding="utf-8")
    else:
        cairn_readme = target_dir / "CAIRN_README.md"
        if not cairn_readme.exists():
            cairn_readme.write_text(readme_content, encoding="utf-8")

    return {
        "status": "initialized",
        "root": str(target_dir),
        "spec": final_spec_path,
        "directories": [str(d.relative_to(target_dir)) for d in dirs],
    }

