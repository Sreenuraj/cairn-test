# cairn-test Practitioner's How-To Guide & Recipes

This guide walks you through using `cairn-test` from your first declarative test through cryptographic approval, strict CI execution, spec-diff healing, and AI IDE integration.

---

## 1. Prerequisites & Installation

`cairn-test` requires **Python 3.12+** and **OpenSSH 8.2+** (for signature verification).

```bash
# Clone the repository
git clone https://github.com/your-org/cairn-test.git
cd cairn-test

# Install in editable mode using uv
uv pip install -e .
```

Verify your installation:
```bash
cairn-test --help
```

---

## 2. End-to-End Walkthrough (Using the Reference Store API)

### Step 1: Start the Reference Store Server
To follow along with a live stateful API, you can launch the bundled reference target server in a separate terminal:
```bash
uv run python -c "
from bench.service.api import start_reference_server
server, url = start_reference_server(8080)
print(f'Reference API listening on {url}')
server.serve_forever()
"
```

### Step 2: Initialize Your Project Scaffold
Run `init` with your OpenAPI specification:
```bash
cairn-test init --spec bench/service/openapi.yaml
```
This scaffolds:
* `cairn.yaml`: Root configuration file (environment profiles, allowed signers).
* `tests/`: Directory for declarative test definitions (`*.test.yaml`).
* `traces/`: Directory for approved baseline traces (`*.trace.yaml`).
* `approvals/`: Directory for cryptographic human approvals (`*.approval.yaml`).
* `proposals/`: Directory for unapproved trace/heal proposals.

### Step 2b: Draft Baseline Tests from Specification
Instead of writing YAML tests by hand, you can automatically draft them from your OpenAPI spec:
```bash
# Option A: Draft directly into tests/ as runnable tests
cairn-test draft --spec openapi.yaml --tests

# Option B: Draft into proposals/, review, and promote
cairn-test draft --spec openapi.yaml
cairn-test review
cairn-test draft --promote
```

### Step 3: Author a Declarative Test
Create `tests/B01-login.test.yaml`:
```yaml
schema: cairn-test.test/v1
id: B01-login
tags:
  - auth
  - smoke
steps:
  - id: do_login
    op: login
    args:
      body:
        username: alice
        password: password123
expect:
  - after: do_login
    status: 200
  - after: do_login
    jsonpath: $.token
    exists: true
  - after: do_login
    jsonpath: $.user
    equals: alice
```

### Step 4: Record Baseline Observations
Record the live HTTP response as an inert trace proposal:
```bash
cairn-test record tests/B01-login.test.yaml
```
Output:
```text
Recorded trace proposal for 'B01-login' -> proposals/B01-login.trace.yaml
```

### Step 5: Review the Proposal
Inspect the pending proposal diff before signing:
```bash
cairn-test review
```
Output displays:
* Plain-language summary of each step.
* Recorded HTTP status code and header shapes.
* Recorded body shape (`token: string`, `user: string`, `expires_in: integer`).
* Auto-masked sensitive fields (PII, tokens, passwords).

### Step 6: Sign Cryptographic Approval
Approve the test using an SSH key (FIDO2 `ed25519-sk`, macOS Secure Enclave, or passphrase-protected Ed25519):
```bash
# Generate a test key if you don't already have one
ssh-keygen -t ed25519 -f ~/.ssh/cairn_dev_key -C "developer@example.com" -N ""

# Sign the approval
cairn-test approve B01-login --key ~/.ssh/cairn_dev_key
```
Output:
```text
Computed canonical coverage hashes:
  - test: 4e91...
  - trace: c81a...
Signed approval with SSH key (ed25519) -> approvals/B01-login.approval.yaml
Promoted trace to traces/B01-login.trace.yaml
```

### Step 7: Run in Dev and Strict Modes
In development mode, you can iterate freely:
```bash
cairn-test run
```

In CI or strict mode, the engine verifies that every test has an unmodified trace and a valid cryptographic signature:
```bash
cairn-test run --strict
```

### Step 8: Diagnose Any Failure with `explain`
`cairn-test` records every execution event in an append-only event store (`.cairn-test/<run-id>/events.sqlite` and `events.jsonl`). You can explain any outcome from stored artifacts alone:
```bash
cairn-test explain <run-id> B01-login
```

---

## 3. Test Authoring Recipes

Here are production-ready YAML test patterns covering all core capabilities.

### Recipe 1: Simple GET with Query Parameters
```yaml
schema: cairn-test.test/v1
id: list-products-paged
tags:
  - products
steps:
  - id: list_prods
    op: getProducts
    args:
      params:
        limit: 5
        offset: 0
expect:
  - after: list_prods
    status: 200
  - after: list_prods
    jsonpath: $.count
    equals: 5
  - after: list_prods
    jsonpath: $.items[0].id
    equals: prod-1
```

### Recipe 2: POST with Request Body and Headers
```yaml
schema: cairn-test.test/v1
id: create-order-coupon
tags:
  - orders
steps:
  - id: create_ord
    op: createOrder
    args:
      headers:
        X-Correlation-ID: corr-12345
      body:
        coupon: SAVE10
        items:
          - sku: prod-2
            qty: 1
            price: 49.98
expect:
  - after: create_ord
    status: 201
  - after: create_ord
    jsonpath: $.total
    equals: 44.98
  - after: create_ord
    jsonpath: $.status
    equals: PLACED
```

### Recipe 3: Multi-Step Chained Workflow (Variable Extraction)
Extract values from earlier steps and interpolate them into subsequent requests using `{variable_name}`:
```yaml
schema: cairn-test.test/v1
id: user-order-lifecycle
tags:
  - integration
steps:
  # Step 1: Login and extract JWT bearer token
  - id: login
    op: login
    args:
      body:
        username: alice
        password: password123
    extract:
      auth_token: $.token

  # Step 2: Create order using extracted token
  - id: create
    op: createOrder
    auth: "{auth_token}"
    args:
      body:
        items:
          - sku: prod-2
            qty: 1
            price: 49.98
    extract:
      new_order_id: $.id

  # Step 3: Fetch order status using extracted order ID
  - id: check
    op: getOrder
    auth: "{auth_token}"
    args:
      id: "{new_order_id}"

expect:
  - after: login
    status: 200
  - after: create
    status: 201
  - after: check
    status: 200
  - after: check
    jsonpath: $.status
    equals: PLACED
```

### Recipe 4: Negative Test Case (Asserting 4xx Errors)
```yaml
schema: cairn-test.test/v1
id: order-empty-items-rejected
tags:
  - orders
  - negative
steps:
  - id: submit_empty
    op: createOrder
    args:
      body:
        items: []
expect:
  - after: submit_empty
    status: 400
  - after: submit_empty
    jsonpath: $.error
    equals: Items cannot be empty
```

### Recipe 5: Property Assertions (Python / CEL Expression)
Assert mathematical relationships across response fields:
```yaml
schema: cairn-test.test/v1
id: order-price-calculation
steps:
  - id: pay
    op: payOrder
    args:
      params:
        id: ord-seed-1
expect:
  - after: pay
    status: 200
  - after: pay
    property: "data.get('paid_amount') == 49.98 and data.get('status') == 'PAID'"
```

### Recipe 6: Setup & Teardown Fixtures
Execute setup steps before the main test and teardown steps after:
```yaml
schema: cairn-test.test/v1
id: temp-order-cancel
fixtures:
  setup:
    - id: prep_order
      op: createOrder
      args:
        body:
          ref: temp-ref
          items:
            - sku: prod-2
              qty: 1
              price: 49.98
  teardown:
    - id: cleanup
      op: cancelOrder
      args:
        id: ord-seed-1
steps:
  - id: cancel
    op: cancelOrder
    args:
      id: ord-seed-1
expect:
  - after: cancel
    status: 200
    jsonpath: $.status
    equals: CANCELLED
```

### Recipe 7: Parameterized Tests
Expand a single test template across multiple test cases:
```yaml
schema: cairn-test.test/v1
id: product-retrieval
parametrize:
  cases:
    - { prod_id: prod-1, expected_name: "Mechanical Keyboard" }
    - { prod_id: prod-2, expected_name: "Wireless Mouse" }
steps:
  - id: get_p
    op: getProduct
    args:
      id: "{prod_id}"
expect:
  - after: get_p
    status: 200
  - after: get_p
    jsonpath: $.name
    equals: "{expected_name}"
```

### Recipe 8: CLI Step Plugin (Domain Neutrality Proof)
Execute local CLI processes as test steps using the built-in CLI plugin:
```yaml
schema: cairn-test.test/v1
id: verify-cli-version
steps:
  - id: run_cli
    plugin: cli
    args:
      command: "echo hello world"
expect:
  - after: run_cli
    status: 0
    jsonpath: $.stdout
    equals: "hello world\n"
```

---

## 4. Maintenance, Blast Radius & Healing Workflows

When an API changes, `cairn-test` eliminates manual test rewriting.

### Analyzing Blast Radius (`impact`)
Given an OpenAPI spec diff (`diff.yaml`), find exactly which tests are affected before running them:
```bash
cairn-test impact --spec-diff diff.yaml
```
Output:
```text
Impact Analysis:
  - Modified Operations: createOrder, getOrder
  - Affected Tests (4):
    * B05-orders-create-single-item
    * B06-orders-create-multi-item
    * B10-compound-step-chain
    * B18-orders-apply-coupon
```

You can then run only the affected tests:
```bash
cairn-test run --changed --spec-diff diff.yaml
```

### Deterministic Healing (`heal`)
For healable fields (`path` rewrite, `operationId` rename, or `params` placement):
```bash
cairn-test heal --spec-diff diff.yaml
```
The healer generates proposals in `proposals/` and runs a dry-run check showing which assertions still hold. It **never alters expectations or test values**.

### Accepting Additive Changes (`accept-observations`)
When new optional fields appear in API responses (benign additions), update your baseline traces in batch without manual editing:
```bash
cairn-test accept-observations
```

---

## 5. Security Diagnostics & CI/CD Integration

### Run the Security Doctor
Audit your local trust root, OpenSSH key type, and environment permissions:
```bash
cairn-test doctor
```
Checks verified:
1. `CAIRN_ALLOWED_SIGNERS` configured and readable.
2. Approved key types (FIDO2 `ed25519-sk` recommended; software keys warned).
3. Canonical LF coverage hash verification.
4. Engine immutability in CI runner.

### Reference GitHub Actions CI Workflow
Add `.github/workflows/cairn-test.yml`:
```yaml
name: cairn-test Verification & Replay

on:
  push:
    branches: [main]
  pull_request:

jobs:
  verify-and-run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install uv and cairn-test
        run: |
          curl -LsSf https://astral.sh/uv/install.sh | sh
          uv pip install -e .

      - name: Set Allowed Signers Trust Root
        env:
          SIGNERS_DATA: ${{ secrets.CAIRN_ALLOWED_SIGNERS }}
        run: |
          mkdir -p ~/.config/cairn-test
          echo "$SIGNERS_DATA" > ~/.config/cairn-test/allowed_signers
          echo "CAIRN_ALLOWED_SIGNERS=$HOME/.config/cairn-test/allowed_signers" >> $GITHUB_ENV

      - name: Strict Verification & Test Replay
        run: |
          cairn-test verify --strict
          cairn-test run --strict --report-format junit --report-file junit.xml

      - name: Publish Test Report
        if: always()
        uses: mikepenz/action-junit-report@v4
        with:
          report_paths: junit.xml
```

---

## 6. AI IDE Pair-Programming (MCP Server)

`cairn-test` includes an embedded Model Context Protocol (MCP) server so AI coding assistants (in Antigravity, Cursor, or Claude Desktop) can safely inspect runs, query blast radius, and propose heals.

### Connecting to the MCP Server
Add to your `claude_desktop_config.json` or `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "cairn-test": {
      "command": "uv",
      "args": ["run", "python", "-m", "cairn_test.core.mcp_server"],
      "cwd": "/path/to/your/repo"
    }
  }
}
```

### Available MCP Tools for the Agent
* `cairn_run`: Execute tests in dev or strict mode.
* `cairn_explain`: Inspect root cause and reason code for any failed or drifted test.
* `cairn_impact`: Query affected tests for a given spec diff.
* `cairn_status`: Check test suite health, flakiness rate, and drift frequency.
* `cairn_propose`: Generate a candidate proposal file in `proposals/` for human review (agent cannot approve).

---

## 7. Enterprise & Multi-Developer Workflows

For guidance on scaling `cairn-test` across multiple engineering teams, see the [Enterprise & Multi-Developer Guide](enterprise-guide.md):
- Managing distributed hardware keys and `.cairn/allowed_signers`
- Modular test repositories without Git merge conflicts
- Headless, zero-secret remote CI/CD runners (GitHub Actions, GitLab CI, Jenkins)
- Cross-team microservice contract drift and blast-radius management
- Production synthetic canaries and alerting models

