# cairn-test: A Trace-Based Test Framework (API-first)

Name: **cairn-test**. A cairn is a stack of stones that marks a trail so others can follow the same path, which is the core idea: record a path once, then follow it reliably. The `-test` suffix is deliberate: the bare name `cairn` is already used by several other tools, including ones that install a `cairn` command, a `cairn.*` config file, and a `.cairn/` directory.

Status: design v1.1. Scope decisions and their rationale are in `core-vision.md` section 5. This file is the source of truth for the design.

## 1. Thesis

Traditional automation pays twice: once to author test code, and again to maintain it. Every API change breaks tests, and a broken test looks the same whether the system changed or the system is wrong.

cairn-test treats a test as **data** and the way to execute it as a **recorded, approved trace**. Replay is deterministic, and **change is reported separately from failure**.

**What v1 must prove (single thesis):**
1. **Correct classification.** Contract changes surface as DRIFT, behavioral bugs as FAIL, benign changes as PASS, and compound cases follow the precedence rules, across a seeded benchmark.
2. **Lower maintenance.** Time to green after contract changes, *including human review time*, is clearly lower than an LLM-assisted Newman suite.

Supporting property, shipped and tested but not a benchmark claim: **tamper-evidence**. In strict mode, no expectation, trace, or config that a human has not signed can influence a result.

Not claimed for v1: lower effort to create tests (business-rule expectations cost the same to think up in any tool), and faster runs through skipping.

Long-term positioning (see `core-vision.md`): a domain-neutral verification layer for AI-written software. API is the first plugin; UI, mobile, and CLI follow on the same core.

## 2. Principles

1. Tests are declarative data. No test code, no inline scripts. The only escape hatch for hard cases is a typed step or assertion plugin.
2. Expectations are human-owned. Tools may draft them; they count only once a human signs an approval.
3. Everything is reviewable: tests, traces, observations, heal proposals, and approvals are readable files.
4. Change is not failure. FAIL (an evaluable expectation was false) and DRIFT (the system no longer matches the recording) are separate outcomes.
5. No model in v1. Execution, healing, drafting, and verdicts are deterministic. Model-assisted resolution is a post-v1 layer that will only ever produce proposals.
6. Every outcome is explainable afterwards from stored artifacts alone.
7. The core knows nothing about HTTP, browsers, or devices. Capabilities come from plugins.
8. Tamper-evident, not tamper-proof: approvals are signed by a human key; strict mode refuses anything unsigned or altered. The limits of this are stated explicitly (section 10).
9. Machine-friendly: every command has structured JSON output and documented exit codes, so coding agents can use it without scraping text.

## 3. Core concepts

| Concept | Meaning |
|---|---|
| Test definition | Human-authored YAML: steps (explicit operations), data bindings, expectations. |
| Trace | Machine-generated record of how each step was executed and what was observed, committed and approved like code. |
| Expectation | A human-approved condition that must hold. Evaluates to `true`, `false`, or `unevaluable`. |
| Observation | The plugin-defined, comparable shape of what a step produced. For API: status, header names, and the structural shape of the body (keys and types). |
| Observation diff | Comparison of a recorded and an observed observation, classified per change as `identical`, `additive`, or `breaking`, with the affected paths listed. |
| Fingerprint | A hash of the inputs a step depends on before it runs (for API: the normalized operation definition). |
| Approval | A signed record binding a human key to the content hashes of a test, its trace, its data, and the config. |
| Evidence | Raw artifacts from a run (requests, responses, timings), masked. |
| Outcome | PASS, FAIL, DRIFT, ERROR, SKIPPED. Assigned only by the core. (CACHED-PASS is reserved for the post-v1 skip feature.) |
| Event | Structured record of everything the engine does. All reporting is built from events. |
| Proposal | A suggested change awaiting human action: a heal (how a step runs), a value request (a human must supply data), an observation update, or a draft test. |

## 4. Architecture

```
            CLI (+ JSON output)      MCP server (later, same API)
                       |
 +---------------------v---------------------+
 |                    CORE                   |
 | planner  scheduler  runner                |  lifecycle, isolation, parallelism
 | outcome engine  event bus                 |  the only place results are decided
 | approval verifier  artifact store  query  |
 +-----+-----------+-----------+-------------+
       |           |           |
  step executor  observer  fingerprinter  assertion  healer  evidence
       \__________ plugin contracts _________/
                       |
             API plugin (v1)     CLI step (v1 proof)     UI / mobile (later)
```

### Plugin contracts (language-neutral; sketched as Python protocols)

```python
class StepExecutor:
    kind: str                                    # e.g. "http"
    def execute(self, step: ResolvedStep, ctx: RunContext) -> StepResult: ...

class Observer:
    def observe(self, result: StepResult) -> Observation: ...
    def compare(self, recorded: Observation, observed: Observation) -> ObservationDiff: ...
        # ObservationDiff.changes: list of {path, kind: identical|additive|breaking, detail}

class Fingerprinter:
    def pre(self, step: ResolvedStep, ctx) -> Fingerprint: ...          # e.g. operation hash
    def touches(self, test: TestDef, trace: Trace) -> list[str]: ...     # e.g. operationIds, for selection

class AssertionType:
    name: str                                    # e.g. "status", "header", "jsonpath", "schema"
    def reads(self, spec: dict) -> list[str]: ...                        # observation paths this check depends on
    def evaluate(self, spec: dict, result: StepResult, ctx) -> AssertionValue: ...  # value or "missing"

class Healer:
    def propose(self, step: ResolvedStep, diff: SpecDiff, ctx) -> Proposal | None: ...

class EvidenceCollector:
    def collect(self, result: StepResult) -> list[Artifact]: ...

class SessionProvider:                           # optional: long-lived state (auth session, later browser)
    def open(self, ctx) -> Session: ...
    def close(self, session: Session) -> None: ...
```

Rules the core enforces:
- Plugins return data, never outcomes. The core decides `true` / `false` / `unevaluable` (section 6.2).
- Plugins never write to the event bus or touch approvals; the core wraps every call and emits events.
- A fake plugin must be able to drive the whole engine.

## 5. Lifecycle and modes

1. **Discover** tests by tags, ids, or `--changed` (spec-diff impact, section 9).
2. **Verify** approvals (strict mode): content hashes and signatures (section 10).
3. **Plan** per test: EXECUTE or SKIPPED (filter or quarantine), with a recorded reason.
4. **Schedule** into isolated workers.
5. **Run** each step: check the pre-fingerprint, execute, observe, compare to the recorded observation, evaluate expectations.
6. **Decide** the outcome in the outcome engine.
7. **Persist** events, evidence, and results; emit reports.

Modes:
- **strict** (CI): approvals verified; missing trace, environment-profile mismatch, or an unapproved or altered file is ERROR; exit code non-zero on FAIL, DRIFT, or ERROR.
- **dev** (local default): same execution, but unapproved content is allowed and the run is marked `untrusted`.
- **record**: execute explicit-`op` steps and write or refresh traces as proposals for approval.
- **heal**: on DRIFT, ask the healer for proposals; never auto-apply.

## 6. Outcomes and rules

### 6.1 Outcomes

| Outcome | Meaning |
|---|---|
| PASS | Executed; every expectation `true`; observation diffs only `identical` or `additive`. |
| FAIL | Executed; at least one evaluable expectation was `false`. Candidate defect. Any drift is attached as detail. |
| DRIFT | No expectation `false`, and at least one of: a `breaking` observation change, a pre-fingerprint mismatch, an `unevaluable` expectation, or a step blocked by drift. Needs triage; usually comes with a proposal. |
| ERROR | Could not produce a meaningful verdict: invalid test, approval failure (strict), missing trace (strict), environment mismatch, transport or auth-setup failure, or a step blocked by an error. |
| SKIPPED | Not executed by choice (filter, tag, quarantine), with a reason. |

Precedence: ERROR > FAIL > DRIFT > PASS. When a higher outcome wins, the lower findings are still reported as detail.

### 6.2 Expectation evaluation

For each expectation the core asks the assertion for the paths it `reads`, then:

1. If the step did not run because an earlier step failed to produce something it needs (e.g. an extracted variable is missing), the expectation is `unevaluable` with cause `blocked-by:<step>`. The cause is DRIFT if the blocking step drifted, ERROR if it errored.
2. Else, if any path it reads appears as `breaking` in the observation diff (removed, type changed, status changed), the expectation is `unevaluable` with the diff entry as its reason.
3. Else it is evaluated: `true` or `false`. A value that is missing with no diff entry to explain it is `false`, not `unevaluable`.

Built-in assertions derive `reads` statically (a JSONPath maps to body paths; `status` reads `status`; `header` reads that header name). Custom assertion types must declare `reads`.

### 6.3 Compound cases (normative)

| Situation | Outcome |
|---|---|
| Contract change only (asserted field renamed) | DRIFT, expectation `unevaluable` |
| Behavioral bug only (wrong total) | FAIL |
| Contract change + unrelated bug in the same test | FAIL, with drift detail |
| Benign additive change (new optional field) | PASS, with an additive note |
| Additive change + bug | FAIL |
| Operation removed (404 on a recorded path) | DRIFT (status is `breaking`); proposal only if the operationId still exists elsewhere |
| Earlier step drifts, later step blocked | DRIFT, later expectations `unevaluable (blocked)` |
| Connection refused | ERROR |

### 6.4 Invariants

1. Only the outcome engine assigns outcomes.
2. Healing may change only the healable trace fields (section 11); never expectations, data values, or test files.
3. Proposals are inert until a human signs an approval.
4. No outcome is converted to PASS automatically.
5. Additive diffs never update a recorded observation silently; updates go through `accept-observations` and a signed approval.
6. Determinism: the same inputs and system state give the same outcomes and report ordering.

## 7. File layout (the user's test project)

```
project/
  cairn-test.yaml           # config: spec location, env profiles, masking rules
  envs/staging.yaml
  data/customers.yaml
  fixtures/                 # reusable setup/teardown steps, as data
  tests/create-order.test.yaml
  traces/create-order.trace.yaml
  approvals/create-order.approval.yaml     # + .sig
  proposals/                # heals, value requests, observation updates, drafts
  reports/                  # gitignored: HTML + JUnit
  .cairn-test/              # gitignored: events DB, evidence
```

Trust root (outside the repository): `allowed_signers` (SSH format) at a path set by user-level config (default `~/.config/cairn-test/allowed_signers`) or supplied by CI.

### Naming conventions

| Item | Convention |
|---|---|
| Distribution (package) name | `cairn-test` |
| Import / module name (Python) | `cairn_test` |
| CLI | `cairn-test <command>` |
| Config | `cairn-test.yaml` |
| Test definitions | `tests/<id>.test.yaml` |
| Traces | `traces/<id>.trace.yaml` |
| Approvals | `approvals/<id>.approval.yaml` + `.sig` |
| Local store | `.cairn-test/` (gitignored) |
| Schema identifiers | `cairn-test.test/v1`, `cairn-test.trace/v1`, `cairn-test.approval/v1`, `cairn-test.proposal/v1`, `cairn-test.event/v1`, `cairn-test.result/v1` |

## 8. Schemas

### Test definition (`cairn-test.test/v1`)

```yaml
schema: cairn-test.test/v1
id: create-order
tags: [orders, smoke]
data:
  customer: { from: data/customers.yaml#guest }
  order_ref: "{run.uid}-order"        # per-worker unique value for data isolation
steps:
  - id: login
    op: login                          # OpenAPI operationId
    args: { user: "{customer.user}", password: "{customer.password}" }
    extract: { token: $.token }
  - id: create
    op: createOrder
    auth: "{token}"
    args: { body: { ref: "{order_ref}", items: [{ sku: SKU-123, qty: 2 }] } }
    extract: { order_id: $.id }
expect:
  - after: create
    status: 201
  - after: create
    jsonpath: $.total
    equals: 49.98
  - after: create
    schema: from-spec
  - state:
      op: getOrder
      args: { id: "{order_id}" }
      jsonpath: $.status
      equals: PLACED
  - after: create                      # optional in v1 (CEL expression)
    property: "body.total == body.items.map(i, i.price * i.qty).sum()"
```

Notes:
- v1 steps use explicit `op` only. `intent` steps are post-v1.
- Values are variables, never recorded literals.
- `{run.uid}` and similar built-ins give each worker isolated data for stateful APIs. Tests that cannot be isolated declare `hermetic: false` and run serially.

### Trace (`cairn-test.trace/v1`)

```yaml
schema: cairn-test.trace/v1
test: create-order
env_profile: staging
spec_hash: a77c...
steps:
  - id: create
    step_hash: 9f2c...                  # hash of the step definition
    resolved:                           # healable fields (section 11)
      operation: createOrder
      method: POST
      path: /orders
      params: { body: [ref, items] }    # where each arg is placed
      headers: { authorization: bearer }
    pre_fingerprint: { op_hash: c40e... }
    observation:
      status: 201
      headers: [content-type, location]
      body_shape: { id: string, total: number, items: [ { sku: string, qty: integer, price: number } ] }
    recorded_at: 2026-11-02T10:00:00Z
```

### Approval (`cairn-test.approval/v1`)

```yaml
schema: cairn-test.approval/v1
subject: create-order
covers:                                 # sha256 of normalized file content
  tests/create-order.test.yaml: 1d4e...
  traces/create-order.trace.yaml: 88a0...
  data/customers.yaml: 0b7c...
  cairn-test.yaml: 5f21...
approver: { name: you, key: "SHA256:Xk3..." }
at: 2026-11-02T10:05:00Z
labels: [new-test]                     # review labels (e.g. weakened, scope-changed); informational
```

The `.sig` file is an SSH signature (`ssh-keygen -Y sign -n cairn-test`) over the canonical approval content.

Every file carries a `schema` version from day one; `cairn-test migrate` upgrades stored files.

## 9. Selection and impact

v1 selection is by tags, ids, and **spec diff**:
- The fingerprinter reports which operations each test touches.
- `cairn-test impact --spec-diff old.yaml new.yaml` lists affected tests and why; `run --changed` runs only those.
- Optional declared mappings (`tests/<id>.test.yaml: touches: [...]`) cover things the spec cannot express.

Code-diff selection (which needs coverage instrumentation) is post-v1. Competitors can do spec-diff selection with external tools too, so v1 reports it as a convenience, not a differentiator.

## 10. Approvals, identity, and the threat model

**Threat model (v1).** A coding agent working in the repository *can* run shell commands, edit any file in the repo, and call any CLI command. It *cannot* use the human's signing key, modify the trust root (`allowed_signers` outside the repo), or merge changes to CI configuration (protected by branch rules or CODEOWNERS). Out of scope: a compromised human machine, or a signing key the agent can use.

**Identity.** Established only by signatures. A human approves with an SSH key that the agent's session cannot use (hardware key with touch, or a passphrase-protected key not loaded in the agent's ssh-agent, or `ssh-add -c` confirmation). Names, flags, and "author kind" fields are labels, not proof.

**Mechanism.**
- `cairn-test approve <id>` computes content hashes of everything the result depends on (test file, trace, referenced data and fixtures, config) and writes a signed approval record.
- In strict mode the core verifies, before running, that every file a test depends on matches a hash in an approval whose signature verifies against the trust root. Any mismatch is ERROR (`unapproved` or `tampered`), and the run fails.
- Because the config is covered, verification cannot be turned off by editing repo config. Strict mode has no bypass flag.

**What any edit means.** Any change to an approved file, including expectations, data bindings, `after:` scope, steps an expectation depends on, or quarantine, invalidates the approval and needs a new signature. Review shows labels to help the human (`expectation-removed`, `operator-loosened`, `scope-changed`, `binding-changed`, `quarantined`), but security does not depend on the labels being complete.

**Honest limits.** Tamper-evident, not tamper-proof. If the agent can use the signing key, or CI does not run strict mode against a trust root the agent cannot change, the guarantee is gone. These assumptions are documented in the CLI's `doctor` output.

## 11. Healing (deterministic, spec-diff based)

Healing is driven by the spec diff, not a model.

**Healable trace fields:** `operation` (only when the operationId is unchanged or explicitly mapped), `method`, `path`, parameter placement (`params`), header mapping (`headers`).

**Not healable:** expectations, data values, args, test files, recorded observations.

Cases:
- Path, method, or parameter location changed, same operationId → **heal proposal**: old and new resolved step, the spec diff, and which expectations still evaluate `true` against a dry run.
- New required parameter → **value request**: a human must supply the value in the test's data. Never invented.
- Asserted response field renamed or removed → **expectation-change request** for human review. Never applied by heal.
- Operation removed with no mapping → DRIFT, no proposal.
- Any FAIL → no heal proposal.

**False heal (formal):** a proposal which, if approved, would change an expectation, a data value, or an arg, or would turn a seeded behavioral bug into PASS.

## 12. Observability

**Event stream** (JSON lines, also in SQLite): `run.started`, `approval.verified`, `test.planned`, `step.executed`, `step.blocked`, `observation.diffed`, `expectation.evaluated`, `test.finished`, `proposal.created`, `approval.signed`, `run.finished`.

**Views** (generated from events and artifacts only):
- **Run view**: outcomes, durations, reasons for every skip, drift, and unevaluable expectation.
- **Test view**: definition, trace, evidence from recent runs, outcome history.
- **Change view**: spec diff, affected tests, proposals.
- **Health view**: drift rate, flaky tests, quarantine list, review time logged.

Exports: JUnit XML; static HTML; SQL-queryable store.

## 13. CLI (v1)

All commands support `--json`. Exit codes are documented and stable.

| Command (`cairn-test <command>`) | Purpose |
|---|---|
| `init --spec openapi.yaml` | Create project, config, import spec. |
| `draft` (optional in v1) | Deterministically draft tests from the spec (status, schema, required-field negatives, auth) into `proposals/`. |
| `record [test]` | Execute and write or refresh traces as proposals. |
| `review` | Walk through proposals and diffs with labels; approve, edit, reject. |
| `approve <id>` | Sign an approval for the current content. |
| `run [--strict] [--tags ..] [--changed]` | Execute with planning and parallelism. |
| `impact --spec-diff a b` | Show affected tests and why. |
| `heal` | Create heal proposals and value requests from a spec diff. |
| `accept-observations` | Batch-propose recorded-observation updates for additive diffs. |
| `explain <run> <test>` | Explain an outcome from stored artifacts. |
| `report` | Build HTML and JUnit output. |
| `migrate` | Upgrade stored files to the current schema versions. |
| `doctor` | Check trust-root, signing-key, and strict-mode assumptions. |
| `bench` | Run the benchmark harness (section 15). |

An MCP server exposing `run`, `explain`, `impact`, `status`, and `propose` over the same API is a "should" in v1, after the CLI is stable.

## 14. API plugin (v1)

- OpenAPI 3.0/3.1 ingestion; normalized per-operation hashing including `$ref`s.
- HTTP executor: JSON request and response bodies (plus status-only checks for other content types), templating, variable binding, JSONPath extraction, auth helpers (bearer, basic, API key, login-and-extract), retries only for transport errors.
- Assertions: `status`, `header`, `jsonpath` (equals, matches, exists, in, range), `schema: from-spec`, `state` (follow-up operation). Optional: `property` (CEL).
- Observer: status, header names, normalized body shape (keys and types; arrays use the merged element shape; key order ignored).
- Diff rules (response, from the observation):

| Change | Class |
|---|---|
| Field added | additive |
| Header added | additive |
| Key order or array length changed | identical |
| Field removed | breaking |
| Field type changed (including number to string, object to array) | breaking |
| Field now observed as `null` where it was never null | breaking |
| Header removed | breaking |
| Status code changed | breaking |

- Diff rules (request side, from the spec diff): new optional parameter is additive; new required parameter, removed parameter, changed type, or changed path/method is breaking (healable when the operationId is unchanged, a value request when a value is needed). Enum values added to a response are additive; removed is breaking.
- Evidence masking: secrets (by name and pattern) and configured PII fields are masked before anything is stored.

## 15. Benchmark

**Target API:** a small stateful reference service (about 12 endpoints: auth, products, orders, refunds) with an OpenAPI spec and switchable seeded changes.

**Behavior catalog:** a fixed list of N = 30 behaviors (`bench/behaviors.yaml`), each implemented in every tool. "Trusted" means every expectation was reviewed by a human; review time is logged.

**Comparators:** Newman (required) and REST Assured (should). Both are built **LLM-assisted with the same coding assistant and time logging** as cairn-test, because that is the realistic 2026 baseline. Keploy is optional context.

**Seeded changes (each labeled with the expected outcome per test):**
- Contract: rename a response field, change a type, add a required parameter, move a parameter, change a path, remove an endpoint.
- Behavioral bugs: wrong total, missing validation, authorization bypass, pagination off-by-one, refund over-limit.
- Benign: new optional field, reordered fields, changed timestamps.
- Compound: contract change + bug in the same test; additive change + bug; drift in step 1 blocking step 3.

**Metrics:**
1. **Classification accuracy** (headline): confusion matrix of expected vs actual outcome per test per seeded change.
2. **Maintenance effort** (headline): wall-clock time to green after each contract change, including human review, for every tool.
3. **Heal quality**: false heals (formal definition, section 11) must be zero; heal acceptance rate.
4. **Create effort** (reported, not claimed): time and authored lines including review.
5. **Speed** (reported): full-suite wall clock and `--changed` run time.
6. **Integrity** (pass/fail check): the tamper suite (requirements FR-V5) is fully rejected in strict mode.

Expected non-wins: create effort, raw request speed, bugs not covered by any expectation, spec-diff selection (others can do it too).

## 16. Out of scope for v1 (post-v1 backlog)

Skip caching and CACHED-PASS (appendix A); `intent` steps and model-assisted resolution or drafting; explore mode; held-out acceptance suites; statistical and differential expectations; suite-strength scoring by fault seeding; code-diff selection; UI and mobile plugins (paper sketch only in v1); XML, multipart, and streaming bodies; GraphQL/gRPC; adapters that run existing pytest or Playwright tests (rejected: conflicts with "no test code" and approvals cannot inspect assertions inside code); hosted dashboards; multi-user workflows; load testing.

## 17. Risks

| Risk | Mitigation |
|---|---|
| The DRIFT/FAIL split breaks on compound cases | Normative compound table (6.3) as test fixtures; compound cases in the benchmark. |
| Shape-based observation misses semantic change | Stated limit: behavior is covered only by expectations; DRIFT is about shape, FAIL is about behavior. |
| Approval fatigue leads to blind signing | Small, labeled diffs; batch approvals for additive updates; review time is measured. |
| Agent can use the signing key | Documented requirement (hardware key, confirm-on-use); `doctor` checks; stated as an honest limit. |
| Core leaks API concepts | Fake plugin tests the core; CLI step implemented as a second plugin; UI paper sketch lists contract pressures. |
| Pull toward scripting | Typed plugins as the only escape hatch; no inline scripts. |
| Non-hermetic stateful tests break parallelism | `{run.uid}` isolation built-ins; `hermetic: false` runs serially. |
| Schema churn | `schema` version on every file; `migrate` command. |

## 18. Open questions (non-blocking for v1)

1. UI observation: accessibility tree, DOM shape, visual hash, or a combination; and its additive/breaking rules.
2. Version-probe design for the post-v1 skip feature.
3. Third-party dependencies in tests (virtual service vs excluded).

## Appendix A: Skip caching (post-v1 design, preserved)

A test may be CACHED-PASS only if all hold: test, trace, and approval hashes unchanged since the last verified PASS; spec hash unchanged for every touched operation; observations unchanged in the last real run; service version unchanged from a configured version probe (no probe means no skipping); data seed and environment profile unchanged; plugin and framework versions unchanged; no recent flakiness; not selected for sampled re-verification. Sampled re-verification reports a false-skip rate. Rationale for deferral: in CI nearly every run follows a deploy, which changes the service version, so the benefit is small compared with the risk and cost.