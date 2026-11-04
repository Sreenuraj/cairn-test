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
base_url: "{base_url}"
timeout_ms: 5000
"""

DEFAULT_STAGING_ENV = """# Staging environment configuration
base_url: "{base_url}"
timeout_ms: 10000
"""

DEFAULT_SCAFFOLD_README = """# {project_name} Test Suite

This test suite is powered by [cairn-test](https://github.com/Sreenuraj/cairn-test), a trace-based, domain-neutral test framework for the AI era.

## 🚀 Quickstart for Humans

### 1. Configure Target Service
Your target endpoint in `envs/local.yaml` was automatically populated from your OpenAPI specification:
```yaml
base_url: "{local_url}"
timeout_ms: 5000
```

### 2. Draft Test Proposals from Specification
Generate deterministic draft proposals directly from your OpenAPI contract:
```bash
cairn-test draft --spec {spec_path}
```
*(Tip: To draft directly into `tests/` as runnable tests in one step, run: `cairn-test draft --spec {spec_path} --tests`)*

### 3. Review & Promote Proposals into Tests
Review the pending proposals and promote them into active tests:
```bash
# Review staged proposals
cairn-test review

# Promote all draft proposals into runnable tests under tests/
cairn-test draft --promote
```

### 4. Record Baseline Observations
Record live API responses into trace proposals:
```bash
# Record all promoted tests in tests/:
cairn-test record

# Or record a specific test:
cairn-test record tests/<test-id>.test.yaml
```

### 5. Review & Sign Cryptographic Approval
```bash
# Inspect recorded traces and diffs
cairn-test review

# Batch-approve all pending proposals (recommended):
cairn-test approve --all

# Or approve a specific test:
cairn-test approve <test-id>
```

### 6. Run the Test Suite
```bash
# Standard dev run
cairn-test run

# Strict verification mode (enforces cryptographic signatures)
cairn-test run --strict
```

---

## 🤖 Instructions for AI Coding Agents (Cursor, Antigravity, Claude, Copilot)

If you are an AI coding assistant working in this repository, follow these rules:

### 1. Draft Tests from Specification
- When asked to create tests from the API specification, generate and promote them:
  ```bash
  # Step 1: Draft proposals from OpenAPI spec
  cairn-test draft --spec {spec_path}

  # Step 2: Promote proposals into runnable tests
  cairn-test draft --promote
  ```
  *(Or in one step: `cairn-test draft --spec {spec_path} --tests`)*
- Tests are Pure Declarative Data: write declarative test definitions in `tests/<test-id>.test.yaml`.
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

### 2. The Untrusted Agent Invariant & Promotion Flow
- As an AI agent, you **CANNOT** sign approvals (`cairn-test approve`). You do not possess the human's hardware private key (`ed25519-sk`).
- When you draft or update a test, execute:
  ```bash
  cairn-test record tests/<test-id>.test.yaml
  ```
  Or to record all drafted tests:
  ```bash
  cairn-test record
  ```
- Then, inform the human developer:
  > *"I have drafted the tests and recorded trace proposals. Please run `cairn-test review` and `cairn-test approve --all` (or `cairn-test approve <test-id>`) with your SSH key."*
- **Never attempt to edit assertions or approved trace hashes** to force a failing test to pass.

### 3. Handling Contract Drift & Spec Changes
- When an API route, parameter, or schema changes in `{spec_path}`, run:
  ```bash
  # Impact analysis against git HEAD:
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

def resolve_spec_servers(spec_file: Path | None, remote_url: str | None = None) -> tuple[str, str, str]:
    """
    Extract best-guess base URLs for (local_url, staging_url, first_op) from an OpenAPI spec and/or remote URL.
    Returns (local_url, staging_url, first_op).
    """
    local_url = "http://127.0.0.1:8000"
    staging_url = "https://staging.example.com"
    first_op = "getHealth"

    origin = None
    if remote_url and (remote_url.startswith("http://") or remote_url.startswith("https://")):
        import urllib.parse
        p = urllib.parse.urlparse(remote_url)
        origin = f"{p.scheme}://{p.netloc}"

    spec_servers: list[str] = []
    if spec_file and spec_file.is_file():
        try:
            content = spec_file.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if isinstance(data, dict):
                # OpenAPI 3.x servers
                if "servers" in data and isinstance(data["servers"], list):
                    for s in data["servers"]:
                        if isinstance(s, dict) and "url" in s and s["url"]:
                            u = s["url"].strip()
                            if u.startswith("/"):
                                if origin:
                                    spec_servers.append(f"{origin}{u}")
                            else:
                                spec_servers.append(u)
                # Swagger 2.0 host & basePath
                elif "host" in data and data["host"]:
                    schemes = data.get("schemes", ["https"])
                    scheme = schemes[0] if schemes else "https"
                    host = data["host"]
                    base_path = data.get("basePath", "")
                    spec_servers.append(f"{scheme}://{host}{base_path}".rstrip("/"))

                # Discover first valid operationId for sample test
                paths = data.get("paths", {})
                if isinstance(paths, dict):
                    for p_path, p_item in paths.items():
                        if isinstance(p_item, dict):
                            for m_name, m_op in p_item.items():
                                if m_name.lower() in ("get", "post", "put", "delete", "patch") and isinstance(m_op, dict):
                                    op_id = m_op.get("operationId")
                                    if op_id:
                                        first_op = op_id
                                        break
                        if first_op != "getHealth":
                            break
        except Exception:
            pass

    if origin and origin not in spec_servers:
        spec_servers.append(origin)

    if spec_servers:
        local_cand = [s for s in spec_servers if "localhost" in s or "127.0.0.1" in s]
        remote_cand = [s for s in spec_servers if not ("localhost" in s or "127.0.0.1" in s)]

        if origin:
            # If initialized from remote URL, prioritize remote origin so record/run works immediately
            local_url = origin
            staging_url = remote_cand[0] if remote_cand else origin
        elif local_cand and remote_cand:
            local_url = local_cand[0]
            staging_url = remote_cand[0]
        elif remote_cand:
            local_url = remote_cand[0]
            staging_url = remote_cand[1] if len(remote_cand) > 1 else remote_cand[0]
        elif local_cand:
            local_url = local_cand[0]
            staging_url = local_cand[1] if len(local_cand) > 1 else local_cand[0]

    return local_url, staging_url, first_op

def init_project(target_dir: Path, spec_path: str | None = None, spec_url: str | None = None) -> dict[str, Any]:
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
    dest_spec_path = None
    if spec_path:
        src_spec = Path(spec_path).expanduser().resolve()
        if src_spec.is_file():
            dest_spec = target_dir / src_spec.name
            if src_spec != dest_spec:
                shutil.copy2(src_spec, dest_spec)
            final_spec_path = src_spec.name
            dest_spec_path = dest_spec
        else:
            final_spec_path = str(spec_path)

    local_url, staging_url, first_op = resolve_spec_servers(dest_spec_path, remote_url=spec_url or spec_path)

    # Write cairn-test.yaml
    cfg_file = target_dir / "cairn-test.yaml"
    if not cfg_file.exists():
        cfg_file.write_text(DEFAULT_CONFIG_CONTENT.format(spec_path=final_spec_path), encoding="utf-8")

    # Write default env files populated with derived URLs
    local_env = target_dir / "envs" / "local.yaml"
    if not local_env.exists():
        local_env.write_text(DEFAULT_LOCAL_ENV.format(base_url=local_url), encoding="utf-8")

    staging_env = target_dir / "envs" / "staging.yaml"
    if not staging_env.exists():
        staging_env.write_text(DEFAULT_STAGING_ENV.format(base_url=staging_url), encoding="utf-8")

    # Write scaffold README with human quickstart & AI agent instructions
    readme_file = target_dir / "README.md"
    readme_content = DEFAULT_SCAFFOLD_README.format(
        project_name=target_dir.name,
        spec_path=final_spec_path,
        local_url=local_url,
    )
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
        "local_url": local_url,
        "staging_url": staging_url,
        "directories": [str(d.relative_to(target_dir)) for d in dirs],
    }

