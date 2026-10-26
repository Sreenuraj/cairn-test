# cairn-test: A Trace-Based Test Framework (API-first)

Name: **cairn-test**. A cairn is a stack of stones that marks a trail so others can follow the same path, which is the core idea: record a path once, then follow it reliably. The `-test` suffix is deliberate: the bare name `cairn` is already used by several other tools, including ones that install a `cairn` command, a `cairn.*` config file, and a `.cairn/` directory.
Status: design draft for v1. See `core-vision.md` for the AI-era rationale behind the core.

## 1. Thesis

Traditional automation pays twice: once to author test code, and again to maintain it. Model-assisted automation adds a third cost, paying tokens to rediscover the same paths on every run.

cairn-test treats a test as **data**, and the way to execute it as a **recorded, reviewable trace**. Resolve once, replay deterministically, skip work when nothing relevant changed, and report change separately from failure. No one writes automation code.

Core claim to prove: lower effort to create, lower effort to maintain, faster feedback after a change, and no loss of accuracy compared with Postman and REST Assured.

AI-era positioning: as coding agents write more of the code, the test suite becomes the main oversight mechanism, and agents are known to game it. cairn-test aims to be **the verification layer for AI-written software: deterministic, tamper-evident, and provenance-tracked**. The core is domain-neutral; API is the first plugin, followed by UI, mobile, and CLI.

## 2. Principles

1. Tests are declarative data. No test code, no step definitions, no page objects.
2. Expectations are human-owned. A tool or model may draft them; they count only once a person approves them.
3. Everything is reviewable: tests, traces, heal proposals, and skip decisions are readable files or records.
4. Change is not failure. FAIL (expectation violated) and DRIFT (the system no longer matches the recording) are separate outcomes.
5. Replay never needs a model. Models are used only to draft, resolve, and propose, never to decide results.
6. Every outcome is explainable after the fact from stored artifacts alone, including skips.
7. The core knows nothing about HTTP, browsers, or devices. Capabilities come from plugins.
8. Safe by default: if a skip cannot be proven safe, run the test.
9. Tamper-evident: every expectation, trace, and proposal records who authored and who approved it. Agents may propose; only people approve. Weakening an expectation is always a separately flagged review item.
10. Agents are first-class users: everything a person can do from the CLI, an agent can do through a structured API/MCP interface, within permissions (run, explain, propose; never approve).

## 3. Core concepts

| Concept | Meaning |
|---|---|
| Test definition | Human-authored YAML: steps (intent or explicit operation), data bindings, expectations. |
| Trace | Machine-generated record of how each step was executed last time, with fingerprints. Committed to the repo, reviewed like code. |
| Expectation | A human-approved condition that must hold after a step or at the end. Evaluated deterministically. |
| Fingerprint | A hash of the inputs a decision depends on (spec, contract, service version, data, env). |
| Observation | The plugin-defined, comparable shape of what a step produced: response contract for API, accessibility tree / DOM shape for UI, exit code and output shape for CLI. Drift, healing, and selection are all defined over observations. |
| Provenance | Who authored and who approved a test, expectation, trace, or proposal, and whether the author was a person, a tool, or an agent. |
| Evidence | Raw artifacts from a run (requests, responses, timings, logs). |
| Outcome | PASS, FAIL, DRIFT, ERROR, CACHED-PASS, SKIPPED. Assigned only by the core. |
| Event | Structured record of everything the engine does. All reporting is built from events. |
| Proposal | A suggested change to a trace (heal), a draft test, or an exploration finding, awaiting approval. |
| Suite strength | How likely a suite is to catch a real defect, measured by seeded faults (mutation-style) per plugin. |

## 4. Architecture

```
            CLI / API
               |
 +-------------v--------------+
 |            CORE            |
 | planner  scheduler  runner |   <- lifecycle, isolation, parallelism
 | outcome engine  event bus  |   <- the only place results are decided
 | artifact store  query API  |
 +---+--------+---------+-----+
     |        |         |
 step executor  fingerprinter  resolver  assertion  evidence/reporters
     \________ plugin contracts ________/
               |
        API plugin (v1)        UI / mobile plugins (later)
               |
        optional model backend (local or none)
```

### Plugin contracts (language-neutral; sketched as Python protocols)

```python
class StepExecutor:
    kind: str                                   # e.g. "http"
    def execute(self, step: ResolvedStep, ctx: RunContext) -> StepResult: ...

class Observer:
    def observe(self, result: StepResult) -> Observation: ...     # plugin-defined comparable shape
    def compare(self, recorded: Observation, observed: Observation) -> ObservationDiff: ...
        # classification: identical | additive (benign) | breaking

class Fingerprinter:
    def pre(self, step: ResolvedStep, ctx) -> Fingerprint: ...    # what must hold before replay
    def inputs_for_skip(self, test: TestDef, trace: Trace, ctx) -> dict[str, str]: ...
    def touches(self, test: TestDef, trace: Trace) -> list[str]: ...  # operations/components/routes, for change-based selection

class SessionProvider:                          # long-lived state: browser context, device, auth session
    def open(self, ctx) -> Session: ...
    def close(self, session: Session) -> None: ...

class FaultSeeder:                              # suite-strength measurement (optional per plugin)
    def seeds(self, ctx) -> list[Fault]: ...

class Resolver:
    def resolve(self, step: StepDef, ctx) -> ResolvedStep: ...    # intent -> concrete operation
    def propose(self, step: StepDef, drift: DriftReport, ctx) -> Proposal: ...

class AssertionType:
    name: str                                   # e.g. "status", "jsonpath", "schema", "state", "property"
    def evaluate(self, spec: dict, result: StepResult, ctx) -> AssertionResult: ...
        # AssertionResult.status: true | false | unevaluable (observation changed so the check cannot apply)

class EvidenceCollector:
    def collect(self, result: StepResult) -> list[Artifact]: ...
```

Rules the core enforces:
- Plugins return data, never outcomes.
- Plugins may not write to the event bus directly; the core wraps their calls and emits events.
- A fake plugin must be able to drive the whole engine (this makes the core testable alone).
- Plugins never see or modify provenance; the core stamps it.

## 5. Lifecycle

1. **Discover** tests matching selection (tags, ids, changed-only via the impact map).
2. **Plan** per test: decide EXECUTE or SKIP, with a recorded reason and the fingerprint comparison.
3. **Schedule** into isolated workers.
4. **Run** each step: load trace, check pre-fingerprint, execute, observe and compare against the recorded observation, evaluate expectations.
5. **Decide** the outcome via the outcome engine.
6. **Persist** events, evidence, results; emit reports.

Modes:
- **strict**: no model, drift fails the run. For CI.
- **record**: resolve unresolved steps (model or explicit), write a trace for review.
- **heal**: on drift, ask the resolver for a proposal; never auto-apply.
- **explore** (later): an exploration agent drives the system without a fixed script and emits findings and draft tests as proposals. Explore results are never verdicts; approved findings become deterministic tests.

## 6. Outcomes and invariants

Precedence when several conditions apply: ERROR > FAIL > DRIFT > PASS.

| Outcome | Meaning |
|---|---|
| PASS | Executed; all expectations held; observation identical or only additively different from the trace. |
| FAIL | Executed; at least one evaluable expectation was false. Candidate defect. |
| DRIFT | Executed or attempted; observation has a breaking difference from the recording (or a precondition mismatch), and no evaluable expectation was false. Expectations that could not apply because of the change are reported as `unevaluable`. Needs triage. |
| ERROR | Could not run meaningfully (connection refused, auth setup failure, invalid test). Not a verdict on the system under test. |
| CACHED-PASS | Not executed; every skip condition proven; last verified result carried forward with evidence. |
| SKIPPED | Not executed by choice (tag, quarantine, filter). |

Invariants:
1. Only the outcome engine assigns outcomes.
2. Healing may change how a step executes, never what is asserted.
3. Proposals are inert files until a person approves them.
4. A DRIFT or FAIL is never converted to PASS automatically.
5. CACHED-PASS requires all skip conditions (section 9), and always records its evidence.
6. A drift detail is reported alongside FAIL when both occur.
7. An expectation is `unevaluable` only when the observation diff explains why (e.g. the asserted field or endpoint is gone). An unexplained missing value is `false`, not `unevaluable`.
8. Statistical expectations (threshold over N samples) are decided once, by the outcome engine, from all recorded samples.
9. A model may contribute advisory evidence (e.g. an LLM-judge score) but never decides an outcome.

Expectation kinds supported by the core: exact (equals, matches, in, range), property/invariant, metamorphic (relation across related inputs), differential (vs a baseline version), and statistical (threshold over samples).

## 7. File layout (the user's test project)

```
project/
  cairn-test.yaml           # config: spec location, model backend, version probe, env profiles
  envs/
    staging.yaml
  data/
    customers.yaml
  tests/
    create-order.test.yaml
  traces/
    create-order.trace.yaml
  proposals/                # drafts and heals awaiting review
  reports/                  # generated static HTML + JUnit XML
  fixtures/                 # reusable setup/teardown and sessions, as data
  acceptance/               # optional held-out suite; agents have no read or write access
  .cairn-test/              # gitignored: events DB, evidence
```

Tests, traces, data, and config are committed. `.cairn-test/` and `reports/` are not.

### Naming conventions

| Item | Convention |
|---|---|
| Distribution (package) name | `cairn-test` |
| Import / module name (Python) | `cairn_test` |
| CLI | `cairn-test <command>` |
| Config | `cairn-test.yaml` |
| Test definitions | `tests/<id>.test.yaml` |
| Traces | `traces/<id>.trace.yaml` |
| Local store | `.cairn-test/` (gitignored) |
| Schema identifiers | `cairn-test.test/v1`, `cairn-test.trace/v1`, `cairn-test.event/v1`, `cairn-test.result/v1` |

## 8. Schemas

### Test definition (`cairn-test.test/v1`)

```yaml
schema: cairn-test.test/v1
id: create-order
tags: [orders, smoke]
data:
  customer: { from: data/customers.yaml#guest }
steps:
  - id: login
    op: login                       # explicit operation (no model needed)
    args: { user: "{customer.user}", password: "{customer.password}" }
    extract: { token: $.token }
  - id: create
    intent: create an order with 2 of SKU-123     # model/resolver maps this to an operation
    auth: "{token}"
    extract: { order_id: $.id }
provenance:
  authored_by: { kind: human, id: you }
  approved_by: { id: you, at: 2026-11-02T10:05:00Z }
expect:
  - after: create
    status: 201
  - after: create
    jsonpath: $.total
    equals: 49.98
  - after: create
    schema: from-spec
  - state:
      request: GET /orders/{order_id}
      jsonpath: $.status
      equals: PLACED
  - after: create
    property: $.total == sum($.items[*].price * $.items[*].qty)
```

Notes:
- A step has either `op` (explicit, deterministic) or `intent` (needs resolving once).
- `schema: from-spec` is a cheap default expectation drafted from the OpenAPI spec.
- Values are variables, never recorded literals.
- `provenance` is stamped by the core on approval. An agent-authored expectation stays inert until a person approves it; a diff that weakens or removes an expectation is flagged separately in review.

### Trace (`cairn-test.trace/v1`)

```yaml
schema: cairn-test.trace/v1
test: create-order
test_hash: 3b1f...
env_profile: { kind: staging, spec_hash: a77c... }
steps:
  - id: create
    step_hash: 9f2c...              # hash of the step definition; change invalidates this step only
    resolved:
      operation: createOrder        # OpenAPI operationId
      method: POST
      path: /orders
      body_template: { items: [{ sku: SKU-123, qty: 2 }] }
    resolved_by: llm                # spec | llm | human
    pre_fingerprint: { op_hash: c40e... }
    observation: { status: 201, response_schema_hash: 51aa..., headers: [content-type] }
    recorded_at: 2026-11-02T10:00:00Z
    approved: { by: you, at: 2026-11-02T10:05:00Z }
```

Every file carries a `schema` version from day one so stored tests can be migrated.

## 9. Change-based selection, fingerprints, and skip policy

**Change-based selection (primary speed mechanism).** Each plugin reports what a test touches (operations, routes, components, files). The core keeps an impact map and selects tests from a spec diff or code diff (`--changed`). This works even without a version probe.

**Skip caching (later optimization).** A test may be CACHED-PASS only if all of these hold:

1. Test hash and trace hash unchanged since the last verified PASS.
2. Spec hash for every operation the test touches unchanged.
3. Observed response contracts unchanged (from the last real run).
4. Service version unchanged, from a configured version probe (header, health endpoint, or build id). **If no version probe is configured, skipping is disabled.**
5. Data seed version and environment profile unchanged.
6. Plugin and framework versions unchanged.
7. Test history is stable (no recent flakiness).
8. The test is not selected for sampled re-verification.

Sampled re-verification: a configurable percentage of cached tests is executed anyway each run, and the disagreement rate is reported as the **false-skip rate**.

Known limit: a contract match means the shape is unchanged, not the behavior. Backend logic changes are only visible through the service version, so the version probe is essential.

## 10. Heal proposals

On DRIFT in heal mode the resolver produces a proposal file: the old step, the new resolved step, the observation diff, and which expectations still pass against it. A person approves or rejects via the CLI. Approval updates the trace, never the expectations. If an expectation also fails, there is no proposal, only a FAIL.

Healing only changes how a step runs. When drift is on the response side (e.g. an asserted field was renamed), the proposal is an *expectation-change request* routed to human review, clearly marked as such, never applied by heal.

## 10a. Verification integrity (AI-era)

- **Provenance everywhere**: tests, expectations, traces, proposals.
- **Weakening detection**: review flags any change that loosens, removes, skips, or quarantines an expectation or test.
- **Held-out acceptance**: an optional `acceptance/` suite that agent sessions cannot read or modify, run by the core on demand.
- **Suite strength**: plugins may provide a `FaultSeeder`; `cairn-test strength` runs the suite against seeded faults and reports a per-suite and per-change score. A falling score after a change is reported like a regression.

## 10b. Agent interface

The engine is exposed as a structured API and an MCP server, with the same capabilities as the CLI:
`impact` (which tests a change affects), `run`, `explain <outcome>`, `propose` (draft, heal, finding), `status`.
Agent sessions get a role with permissions: run, explain, propose. They never approve, edit expectations, or read held-out suites. All agent actions are events with provenance.

## 11. Observability

**Event stream** (JSON lines, also stored in SQLite): `run.started`, `test.planned` (decision + reason), `step.replayed`, `step.resolved`, `step.drift`, `expectation.evaluated`, `test.finished`, `heal.proposed`, `proposal.approved`, `expectation.weakened`, `agent.action`, `strength.measured`, `run.finished`.

**Views** (all generated from events and artifacts, no special cases):
- **Run view**: outcomes, durations, reason for every skip and drift.
- **Test view**: definition, current trace, evidence from recent runs, outcome history.
- **Change view**: per build, what changed (endpoints, schemas) and which tests it touches.
- **Health view**: cache-hit rate, drift rate, flaky tests, time saved, false-skip rate.

Exports: JUnit XML for CI; static HTML for reading; the store is queryable by SQL.

## 12. CLI (v1)

| Command (run as `cairn-test <command>`) | Purpose |
|---|---|
| `init --spec openapi.yaml` | Create project, config, import spec. |
| `draft` | Generate draft tests and proposed expectations from the spec into `proposals/`. |
| `review` | Walk through proposals; approve, edit, or reject. |
| `record [test]` | Resolve steps and write traces for approval. |
| `run [--strict] [--tags ..] [--changed]` | Execute with planning, skip logic, parallelism. |
| `diff` | Show what changed in the system under test since the last verified run. |
| `heal` / `approve <id>` | Generate and apply trace proposals. |
| `report` | Build static HTML and JUnit output. |
| `bench` | Run the benchmark harness (section 14). |
| `impact [--diff ..]` | Show which tests a spec or code change affects. |
| `strength` | Run the suite against seeded faults and report suite strength. |
| `mcp` | Start the MCP server for coding agents (section 10b). |

## 13. API plugin (v1)

- OpenAPI 3 ingestion; operation-level hashing including referenced schemas.
- HTTP step executor with variable binding, extraction (JSONPath), auth helpers, retries only for ERROR classification.
- Assertion types: status, header, jsonpath (equals, matches, exists, in), schema (from-spec), state (follow-up request).
- Fingerprinter: operation hash (pre), response contract hash (post), version probe.
- Resolver: explicit `op` resolved deterministically; `intent` resolved via a model that maps to an operationId and arguments, constrained to operations in the spec. Backend is pluggable (local model such as Ollama, or none, in which case intent steps are unsupported).
- Draft generator: happy path, boundaries, required-field and type negatives, auth variations, from the spec. Output is drafts only.

## 14. Benchmark (proof that it is better)

**Target API**: a small stateful reference service (about 15 endpoints: auth, products, orders, payments, refunds) with a switchable set of seeded changes.

**Comparison suites**: equivalent tests written in cairn-test, Postman/Newman, and REST Assured, covering the same behaviors.

**Reference point**: Keploy (open-source; records real API traffic and replays it as tests and mocks) is established prior art for the record-and-replay half of this idea. It is an optional comparator. cairn-test's differences to demonstrate are the DRIFT/FAIL split, skip decisions with evidence, human-owned expectations, and heal-as-proposal, not record-and-replay itself.

**Seeded changes**
- Contract changes (should surface as DRIFT, with affected expectations marked `unevaluable`, plus a heal proposal or an expectation-change request): rename a field, change a type, add a required parameter, remove an endpoint.
- Behavioral bugs (should be FAIL): wrong total calculation, missing validation, authorization bypass, pagination off-by-one, refund over-limit.
- Benign changes (should not fail): new optional field, reordered fields, changed timestamps.

**Metrics**
1. **Create effort**: time and authored lines to get N tests from spec to trusted and passing.
2. **Maintenance effort**: time to green after each contract change.
3. **Accuracy**: bugs caught, false failures, false heals, false skips.
4. **Speed**: full-suite wall clock, and incremental run time after a small change.
5. **Integrity** (AI-era): a scripted "agent" attempts to make failing tests green by weakening expectations, skipping tests, or editing traces; measure how many attempts are blocked or flagged.

Additional comparators for context: Hurl / Step CI (declarative API tests), Schemathesis (spec-driven generation), Playwright Test Agents (AI healer over code).

Hypotheses (targets to validate, not claims): much lower create and maintenance effort than REST Assured and Newman; zero false heals; false-skip rate near zero; faster incremental feedback. Expected non-wins: single-test setup, raw request speed, and bugs not covered by any expectation.

## 15. Out of scope for v1

UI and mobile plugins (designed on paper in v1, built later), the explore mode, hosted dashboard, model-approved expectations, load and performance testing, multi-user collaboration features.

## 16. Risks

| Risk | Mitigation |
|---|---|
| Wrong skip because a dependency is missing from the fingerprint | Require version probe; sampled re-verification; report false-skip rate; seeded-change benchmark. |
| Frozen misresolution (model misreads an intent once) | Mandatory trace review with readable rendering; prefer explicit `op` for critical steps. |
| Proposal fatigue leading to blind approval | Small diffs, grouped proposals, show which expectations still hold. |
| Core leaks API concepts and blocks later plugins | Fake plugin tests the core; design a UI plugin on paper (sessions, waits, nondeterminism, visual evidence) before freezing contracts; implement CLI as the cheap second plugin. |
| DRIFT/FAIL split collapses because changed contracts make expectations fail | `unevaluable` status driven by the observation diff; compatibility-aware diffs (identical / additive / breaking). |
| Agents game the suite (weaken, skip, special-case) | Provenance, weakening detection, held-out acceptance suite, suite-strength scoring, agents can never approve. |
| Pull toward scripting for hard cases turns the tool back into code | Typed assertion and step plugins as the only escape hatch; no inline scripts in test files. |
| Non-hermetic tests make skipping and parallelism unsafe | Per-test setup and teardown; mark non-hermetic tests as never skippable. |
| Contract and schema churn | Version every format from day one; provide a migration command. |

## 17. Open questions

1. Language for the reference implementation (leaning Python; contracts are JSON-Schema-first so this stays swappable).
2. Version probe design for services with no version endpoint.
3. How to treat tests that call third-party services (virtual service vs exclude from skipping).
4. What a UI Observation is exactly (accessibility tree, DOM shape, visual hash, or a combination) and how additive vs breaking is defined for it.
5. Default sample count and threshold semantics for statistical expectations.