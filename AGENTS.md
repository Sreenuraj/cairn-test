# Cairn-Test: Development Guidelines, Architectural Rules & Learnings

This repository contains **cairn-test**, a trace-based, domain-neutral test and governance framework designed for the AI era. All AI agents and human contributors operating in this codebase MUST adhere strictly to the following architectural rules, ergonomic principles, and learnings.

---

## 1. Core Architectural Invariants

### 1.1 Import Isolation (NFR-8)
* `cairn_test.core` MUST NEVER import HTTP client libraries (`requests`, `httpx`, `aiohttp`, `urllib3`, `http.client`), browser automation libraries (`playwright`, `selenium`, `puppeteer`), or AI model SDKs (`openai`, `anthropic`, `google.genai`, `transformers`, `torch`, `langchain`).
* `cairn_test.core` is strictly domain-neutral: schema validation, canonical LF SHA-256 covers, approval verification, scheduler/planner logic, and event orchestration.
* All external interactions (HTTP, browser, DB, CLI) belong exclusively inside plugins (`cairn_test.plugins.*`).
* Verification: NFR-8 is strictly enforced by `tests/test_core_skeleton.py::test_nfr8_core_import_isolation`. This test must always run in an isolated subprocess to prevent ambient test runner plugins (e.g., `pytest-playwright`) from polluting `sys.modules`.

### 1.2 Untrusted Agent Invariant & Governance Philosophy
* AI coding agents and automated scaffolders are **untrusted proposers**.
* Automated tools, spec drafters, and self-healing algorithms MUST NOT silently mutate approved baselines or inject unreviewed tests directly into `tests/` without human visibility.
* All automated proposals MUST land in `proposals/*.proposal.yaml`.
* Only human approvals (`approvals/*.approval.yaml`) signed with hardware-backed OpenSSH keys (`ed25519-sk` / Secure Enclave) grant authority over canonical LF SHA-256 covers.
* In strict CI/remote environments (`cairn-test run --strict`), unapproved tests or tampered files exit with non-zero status.

---

## 2. CLI Ergonomics & UX Rules (Learnings from Dogfooding)

### 2.1 Dual Target Syntax: Positional & Flag Support
Users and agents oscillate between positional arguments and flag options. Every CLI command that targets a test ID MUST accept both styles seamlessly:
* `cairn-test record tests/sample.test.yaml` AND `cairn-test record --id sample-health-check`
* `cairn-test review sample-health-check` AND `cairn-test review --id sample-health-check`
* `cairn-test approve sample-health-check` AND `cairn-test approve --id sample-health-check`
* `cairn-test verify sample-health-check` AND `cairn-test verify --id sample-health-check`

### 2.2 Template & Example File Fallback
* When a command targets a file (e.g. `tests/sample.test.yaml`) that currently only exists as a template (e.g. `tests/sample.test.yaml.example`), the CLI must automatically copy the template into place and proceed rather than failing with an error.

### 2.3 Draft-to-Test Promotion Lifecycle
* `cairn-test draft --spec <spec>` writes staged proposals to `proposals/` by default.
* `cairn-test review` MUST discover and report both tests in `tests/` AND pending draft proposals in `proposals/` so `review` / `review --json` never return empty when drafts exist.
* `cairn-test draft --promote` promotes staged draft proposals into active `tests/<id>.test.yaml` definitions.
* `cairn-test draft --spec <spec> --tests` provides a direct 1-step draft path into `tests/` for developers wanting immediate runnable tests.
* `cairn-test approve <draft_id>` automatically promotes the draft proposal into `tests/` upon signing.
* Always print actionable hints in human CLI outputs (e.g. recommending `cairn-test draft --promote` or `cairn-test record`).

### 2.4 Spec-Aware Scaffolding & Zero Dummy Pollution
* When scaffolding a project via `cairn-test init --spec <url_or_file>`:
  - Base URLs for `envs/local.yaml` and `envs/staging.yaml` MUST be automatically derived from OpenAPI `servers` and/or the remote URL origin rather than hardcoding dummy placeholders (`localhost:8000`).
  - Do NOT generate dummy data files (e.g. fake user credentials in `data/customers.yaml`). Scaffold only what is necessary and keep directories clean.
  - The sample test template (`tests/sample.test.yaml.example`) must use the first valid operation found in the target spec so recording exercises real API surface.

---

## 3. Engineering & Code Standards (Senior Dev Mode)

1. **First Rung That Holds (YAGNI & Simplicity)**:
   - Check if standard library already provides the capability before reaching for third-party libraries.
   - Zero unnecessary dependencies. The core framework runtime relies only on `pyyaml` and `jsonschema`.
   - Boring over clever. Shortest working diff wins once the root cause is understood.
2. **Root Cause Over Symptom**:
   - When a bug or missing capability is reported on one command, grep all sibling commands and callers. Fix the pattern globally rather than patching only the reported path.
3. **No Unchecked Logic**:
   - Every non-trivial logic change MUST leave behind at least ONE runnable check in `tests/` that exercises the behavior end-to-end and will fail if the logic breaks.
4. **Security & Zero Secret Leaks**:
   - Hardware keys (`id_ed25519_sk`), private keys, `.env` files, and credentials MUST NEVER be committed to Git.
   - Always run `git diff --cached` and verify `.gitignore` before committing.

---

## 4. Package Installation & Local Development Sync

* When developing locally, always install the package in editable mode:
  ```bash
  pip install -e .
  # or
  uv pip install -e .
  ```
* In editable mode, changes to Python files in `src/cairn_test/` take effect **immediately** across all shell executions without needing to uninstall or reinstall.
* Only re-run `pip install -e .` if new console scripts or entry points are modified in `pyproject.toml`.
