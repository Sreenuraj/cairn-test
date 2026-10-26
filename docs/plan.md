# cairn-test: A Trace-Based Test Framework (API-first)

Name: **cairn-test**. A cairn is a stack of stones that marks a trail so others can follow the same path, which is the core idea: record a path once, then follow it reliably. The `-test` suffix is deliberate: the bare name `cairn` is already used by several other tools, including ones that install a `cairn` command, a `cairn.*` config file, and a `.cairn/` directory.

Status: design v1.2. Scope decisions and their rationale are in `core-vision.md` section 5. This file is the source of truth for the design.

## 1. Thesis

Traditional automation pays twice: once to author test code, and again to maintain it. Every API change breaks tests, and a broken test looks the same whether the system changed or the system is wrong.

cairn-test treats a test as **data** and the way to execute it as a **recorded, approved trace**. Replay is deterministic, and **change is reported separately from failure**.

**What v1 must prove (single thesis):**
1. **Correct classification.** Contract changes surface as DRIFT, behavioral bugs as FAIL, benign changes as PASS, and compound cases follow the precedence rules, across a seeded benchmark.
2. **Lower maintenance.** Time to green after contract changes, *including human review time*, is clearly lower than an LLM-assisted Newman suite that is given the same spec diff.

Where the maintenance advantage is expected to come from (no model in v1), in order of expected size:
1. **Triage.** A contract change produces DRIFT with the exact observation diff and the list of affected expectations, instead of a wall of red assertion failures that a person (or assistant) has to sort into "changed" and "broken".
2. **Impact.** The spec diff selects exactly the affected tests.
3. **Deterministic repair.** Request-side heals (path, method, parameter placement, operationId rename) and rename/move suggestions for response fields, each applied only after approval.

Fix time is expected to be only modestly faster than an LLM-assisted competitor; triage is where the claim must hold. The benchmark measures triage time and fix time separately (section 15). If triage shows no advantage, the thesis fails.

Supporting property, shipped and tested but not a benchmark claim: **tamper-evidence**. When strict mode runs in CI with a pinned engine and a trust root the agent cannot change, no expectation, trace, config, or project plugin that a human has not signed can influence a result (threat model: section 10).

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
8. Tamper-evident, not tamper-proof: approvals are signed with a human key that needs a physical action per signature; strict mode refuses anything unsigned or altered. The guarantee holds where verification runs out of the agent's reach (CI with a pinned engine); locally it is advisory. Limits are stated explicitly (section 10).
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
  plugins/                  # optional project-local plugins (code, covered by approvals)
  tests/create-order.test.yaml
  traces/create-order.trace.yaml
  approvals/create-order.approval.yaml     # + .sig
  proposals/                # heals, value requests, observation updates, drafts
  reports/                  # gitignored: HTML + JUnit
  .cairn-test/              # gitignored: events DB, evidence
```

Trust root (outside the repository): `allowed_signers` (SSH format). In CI it comes from a CI variable (`CAIRN_ALLOWED_SIGNERS`) that the agent's credentials cannot edit. Locally it comes from user-level config (default `~/.config/cairn-test/allowed_signers`) and is advisory only (section 10).

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
  plugins/discount_rule.py: 9e3a...     # project-local plugin code the test uses
approver: { name: you, key: "SHA256:Xk3...", key_type: sk-ssh-ed25519@openssh.com }
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

### 10.1 Threat model (v1)

The agent runs as the same OS user as the human, in the same repository.

| The agent can | The agent cannot (assumed) |
|---|---|
| Run any shell command as the user | Produce a signature with the human's key (10.2) |
| Edit any file in the repo, in `~/.config`, and in the local cairn-test install | Edit CI workflow files or CI variables, or push to `main` (10.3) |
| Run any CLI command, including `approve` | Change which cairn-test version CI runs (pinned in the workflow) |
| Push branches and open pull requests | |

Consequence: **anything that runs on the human's machine can be tampered with by the agent**, including the local trust root and the installed engine. Local strict mode is therefore *advisory*. The guarantee comes from **CI**, which runs a pinned engine against a trust root the agent cannot reach.

Out of scope: a compromised CI provider, a compromised human, and a human who confirms a signature without reading what is being signed.

### 10.2 Where the signing key lives

"The agent cannot use the key" is only true for keys that need a physical human action on **every** signature:

| Key setup | Supported? | Why |
|---|---|---|
| FIDO2 security key, `ed25519-sk` (touch per signature; PIN with `-O verify-required`) | **Recommended** | The private key never leaves the device; each signature needs a touch. |
| Secure Enclave key with Touch ID per use (e.g. Secretive on macOS) | **Supported** | Not exportable; each signature needs Touch ID. |
| Passphrase-protected key file, never added to an ssh-agent, passphrase typed per approval | Tolerated, with a warning | The agent can read the file but cannot use it without the passphrase. Weaker: offline guessing is possible. |
| Key loaded in an ssh-agent without per-use confirmation, or an unencrypted key file | **Not supported** | Anything running as the user can sign. |
| `ssh-add -c` confirmation | Not recommended | Depends on an askpass dialog that is easy to misconfigure. |

`approve` records the key type in the approval and warns when it is not a security-key type. The CI trust root should list only keys of the supported kinds. CI never holds a signing key; it only verifies.

**Unexpected prompts.** The agent can run `approve` itself, which makes the key ask for a touch. Rule for humans: touch only when you started the approval yourself, after `approve` has shown the summary of what will be signed. `approve` always prints the subject, labels, and covered files before asking for the signature.

### 10.3 Where verification is enforced

For the guarantee to hold in CI:
- The workflow installs cairn-test **pinned in the workflow file** (container image digest or hash-pinned package), not from a repo lockfile the agent can edit.
- The trust root comes from a CI variable (`CAIRN_ALLOWED_SIGNERS`).
- The agent's git credential is a fine-grained token or deploy key that can push branches but has **no workflow permission, no admin rights, and cannot push to `main`** (repository ruleset).
- `main` requires the strict CI check to pass.

Locally, `cairn-test verify` and strict runs give the same answers, but treat them as a convenience: an agent that wanted to fake them could.

### 10.4 Mechanism

- `cairn-test approve <id>` shows what will be signed. It then computes content hashes of everything the result depends on: the test file, trace, referenced data and fixtures, config, and **the source of any project-local plugin** the test uses. Finally it writes a signed approval record.
- Before running, strict mode verifies that every one of those files matches a hash in an approval whose signature verifies against the trust root. Any mismatch is ERROR (`unapproved`, `tampered`, `bad-signature`, `unknown-signer`), and the run fails.
- Because config and project plugins are covered, editing repo files cannot weaken verification. Strict mode has no bypass flag.
- Plugins installed as packages are covered by the pinned engine in CI, not by approvals.

### 10.5 What any edit means

Any change to an approved file invalidates the approval and needs a new signature. That includes expectations, data bindings, `after:` scope, steps an expectation depends on, quarantine, and plugin code. Review shows labels to help the human (`expectation-removed`, `operator-loosened`, `scope-changed`, `binding-changed`, `quarantined`, `plugin-changed`), but security does not depend on the labels being complete.

### 10.6 Honest limits

Tamper-evident, not tamper-proof, and only within 10.1. The guarantee is gone if any of these hold: the key can sign without a human action; CI does not run strict mode with a pinned engine and a protected trust root; or the human signs without reading. `doctor` reports the assumptions it can check: key type, trust-root source, and whether the CI workflow pins the engine.

## 11. Healing (deterministic, spec-diff based)

Healing is driven by the spec diff, not a model.

**Healable trace fields:** `operation` (only when the operationId is unchanged or explicitly mapped), `method`, `path`, parameter placement (`params`), header mapping (`headers`).

**Not healable:** expectations, data values, args, test files, recorded observations.

Cases:
- Path, method, or parameter location changed, same operationId → **heal proposal**: old and new resolved step, the spec diff, and which expectations still evaluate `true` against a dry run.
- OperationId renamed while method, path, and schemas stay identical → heal proposal mapping the old operationId to the new one.
- New required parameter → **value request**: a human must supply the value in the test's data. Never invented.
- Asserted response field renamed or moved → **expectation-change request with a suggested edit**. The spec diff shows a field removed and a field of the same type added, in the same object (rename) or in a nested object (move). The suggestion rewrites only the JSONPath, never the expected value or operator. It is labeled as an expectation change and needs a signature like any other edit.
- Asserted response field removed with no candidate, or type changed → expectation-change request without a suggestion.
- Operation removed with no mapping → DRIFT, no proposal.
- Any FAIL → no heal proposal and no suggestion.

If several fields could be the rename target, there is no suggestion. Precision matters more than coverage here.

**False heal (formal):** a *heal proposal* which, if approved, would change an expectation, a data value, or an arg, or would turn a seeded behavioral bug into PASS.

**Masking suggestion (formal):** an expectation-change suggestion which, if approved, would turn a seeded behavioral bug into PASS. Both counts must be zero.

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
| `approve <id>` | Show what will be signed, then sign an approval for the current content. |
| `verify` | Check every approval against the trust root without running tests (CI runs this first). |
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

**Pre-registration.** Before any suite is written, `bench/preregistration.md` fixes:
- the 30 behaviors, and the core subset of 12 used if checkpoint E1 falls back (`tasks.md`);
- every seeded change, with the expected outcome per test and the expected repair mechanism;
- the metrics and the analysis (medians over at least 3 runs);
- the success and kill thresholds.

It is committed with a signed tag (`prereg-v1`) and not edited afterwards. Any change goes into `bench/deviations.md` with a reason and date, and results are reported against both the original and the amended version.

Order of work: write the pre-registration; write all suites against the unchanged target and tag them (`suites-frozen`, signed); only then switch on seeded changes, by script. Edits to a suite after that point are the measured maintenance work, never tuning. Maintenance runs are not blind (the same person sees the changes in every tool), but they are symmetric.

**Behavior catalog:** a fixed list of N = 30 behaviors (`bench/behaviors.yaml`), each implemented in every tool. "Trusted" means every expectation was reviewed by a human; review time is logged.

**Comparators:** Newman (required) and REST Assured (should). Both are built and maintained **LLM-assisted, with the same coding assistant and time logging** as cairn-test, because that is the realistic 2026 baseline. During maintenance every tool gets the same inputs: the failing run output and the spec diff. Keploy is optional context.

**Seeded changes (each labeled with the expected outcome per test and the expected mechanism):**
- Contract, request side: move a parameter (query to body), change a path, rename an operationId, add a required parameter. Expected: heal, heal, heal, value request.
- Contract, response side: rename a field, move a field into a nested object, change a type, remove an endpoint. Expected: suggestion, suggestion, request without a suggestion, no proposal.
- Behavioral bugs: wrong total, missing validation, authorization bypass, pagination off-by-one, refund over-limit.
- Benign: new optional field, reordered fields, changed timestamps.
- Compound: a contract change and a bug in the same test; a rename plus a bug on the renamed field; an additive change plus a bug; drift in step 1 blocking step 3.

**Metrics:**
1. **Classification accuracy** (headline): confusion matrix of expected vs actual outcome per test per seeded change.
2. **Maintenance effort** (headline), measured in two parts for every tool, both including human review:
   - *Triage time*: from the red run to a correct written list of which tests are affected, and whether each is a contract change or a defect.
   - *Fix time*: from triage to green, with every edit approved (cairn-test) or reviewed (the others).
3. **Repair quality**: false heals and masking suggestions (section 11) must both be zero; heal and suggestion acceptance rates.
4. **Create effort** (reported, not claimed): time and authored lines including review.
5. **Speed** (reported): full-suite wall clock and `--changed` run time.
6. **Integrity** (pass/fail check): the tamper suite (requirements FR-V5) is fully rejected in strict mode.

Expected non-wins: create effort, raw request speed, bugs not covered by any expectation, spec-diff selection (others can do it too), and fix time on simple request-side changes (an LLM-assisted competitor can fix a URL quickly too).

## 16. Out of scope for v1 (post-v1 backlog)

Skip caching and CACHED-PASS (appendix A); `intent` steps and model-assisted resolution or drafting; explore mode; held-out acceptance suites; statistical and differential expectations; suite-strength scoring by fault seeding; code-diff selection; UI and mobile plugins (paper sketch only in v1); XML, multipart, and streaming bodies; GraphQL/gRPC; adapters that run existing pytest or Playwright tests (rejected: conflicts with "no test code" and approvals cannot inspect assertions inside code); hosted dashboards; multi-user workflows; load testing.

## 17. Risks

| Risk | Mitigation |
|---|---|
| The DRIFT/FAIL split breaks on compound cases | Normative compound table (6.3) as test fixtures; compound cases in the benchmark. |
| Shape-based observation misses semantic change | Stated limit: behavior is covered only by expectations; DRIFT is about shape, FAIL is about behavior. |
| Approval fatigue leads to blind signing | Small, labeled diffs; batch approvals for additive updates; review time is measured. |
| Agent can use the signing key | Only keys that need a touch or Touch ID per signature are supported (10.2); `approve` records the key type and warns; stated as an honest limit. |
| Agent tampers with the local engine or trust root | Local verification is advisory. The guarantee comes from CI, with a pinned engine, a trust root in a CI variable, and an agent credential that has no workflow or `main` access (10.3). |
| No maintenance advantage without a model | Triage and fix time measured separately; the thesis rests on triage and is killed if triage shows no advantage. |
| Benchmark tuned after seeing results | Signed pre-registration tag before any suite; suites frozen before seeded changes; deviations log; results reported against the original and amended versions. |
| Rename suggestions guess wrong | Only unambiguous same-type candidates; the rewrite changes only the JSONPath; masking suggestions must be zero. |
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