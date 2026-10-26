# cairn-test Requirements (v1)

Companion to `plan.md` and `core-vision.md`. IDs are stable so tasks and tests can reference them.
Priority: **M** = must for v1, **S** = should, **C** = could.

## 1. Users and constraints

- Primary user: the author, running locally. No servers, accounts, or hosted components.
- Everything that defines a test or its execution is a file in git.
- A model is optional. The system must work end to end with no model for explicit-`op` tests.
- Secondary user: coding agents acting on the author's behalf, through a permissioned interface.

## 2. Functional requirements

### Core engine
| ID | Requirement | P |
|---|---|---|
| FR-C1 | Load test definitions (`cairn-test.test/v1`) and validate them against a JSON Schema with clear errors. | M |
| FR-C2 | Load and validate traces (`cairn-test.trace/v1`); reject unknown schema versions with a migration hint. | M |
| FR-C3 | Plan each test as EXECUTE or SKIP, recording the reason and the fingerprint comparison. | M |
| FR-C4 | Execute tests in isolated workers with configurable parallelism. | M |
| FR-C5 | Assign outcomes only in the outcome engine, following the precedence ERROR > FAIL > DRIFT > PASS. | M |
| FR-C6 | Support outcomes PASS, FAIL, DRIFT, ERROR, CACHED-PASS, SKIPPED with the meanings in `plan.md`. | M |
| FR-C7 | Emit structured events for every lifecycle stage; persist to JSONL and SQLite. | M |
| FR-C8 | Store evidence per step (request, response, timing) linked to the event stream. | M |
| FR-C9 | Provide modes: strict, record, heal. Strict must never call a model. | M |
| FR-C10 | A fake plugin must be able to drive the full lifecycle, including each outcome. | M |
| FR-C11 | Tag-based selection, id-based selection, and `--changed` selection. | S |
| FR-C12 | Configurable per-test timeout and per-run budget. | S |
| FR-C13 | Expectation results are `true`, `false`, or `unevaluable`; `unevaluable` is allowed only when the observation diff explains it, and yields DRIFT rather than FAIL. | M |
| FR-C14 | Observation comparison classifies differences as identical, additive, or breaking; only breaking differences yield DRIFT. | M |
| FR-C15 | Core expectation kinds: exact, property/invariant, metamorphic, differential (vs baseline), statistical (threshold over N samples). | S |
| FR-C16 | Fixtures and setup/teardown as data; parameterized tests; long-lived sessions via plugins. | S |
| FR-C17 | Flake tracking and quarantine (quarantined tests are SKIPPED with a reason). | S |

### Plugin contracts
| ID | Requirement | P |
|---|---|---|
| FR-P1 | Define language-neutral contracts for StepExecutor, Observer, Fingerprinter, SessionProvider, Resolver, AssertionType, EvidenceCollector, and (optional) FaultSeeder. | M |
| FR-P2 | Plugins return data only; the core wraps all calls and emits events. | M |
| FR-P3 | New step types and assertion types can be added without modifying core code. | M |
| FR-P4 | Plugin and framework versions are part of fingerprints. | M |
| FR-P5 | Contracts are validated on paper against a UI plugin design (sessions, waits, nondeterminism, visual evidence) before being frozen. | M |

### API plugin
| ID | Requirement | P |
|---|---|---|
| FR-A1 | Ingest OpenAPI 3.x; compute normalized per-operation hashes including referenced schemas. | M |
| FR-A2 | Execute HTTP steps with variable binding, JSONPath extraction, and header/body templating. | M |
| FR-A3 | Assertion types: status, header, jsonpath (equals, matches, exists, in, range), schema from spec, follow-up state request. | M |
| FR-A4 | Record the observed response contract (status, schema hash, header names) per step. | M |
| FR-A5 | Detect drift between recorded contract and observed contract; classify as DRIFT when no expectation fails. | M |
| FR-A6 | Auth helpers (bearer, basic, API key, login-and-extract). | M |
| FR-A7 | Resolve `intent` steps to an operationId and arguments, constrained to operations present in the spec. | S |
| FR-A8 | Generate draft tests and proposed expectations from the spec (happy path, boundaries, negatives, auth). | S |
| FR-A9 | Version probe configuration (header, endpoint, or build id) feeding the skip fingerprint. | M |

### Authoring, review, and healing
| ID | Requirement | P |
|---|---|---|
| FR-R1 | `init` creates a project from an OpenAPI spec. | M |
| FR-R2 | `draft` writes drafts to `proposals/`; drafts are inert until approved. | S |
| FR-R3 | `review` lets a person approve, edit, or reject drafted tests and expectations. | M |
| FR-R4 | `record` resolves steps, writes traces, and renders each step in plain language for approval. | M |
| FR-R5 | Traces are committed only through an explicit approval step that stamps who and when. | M |
| FR-R6 | Heal produces proposals containing old step, new step, contract diff, and which expectations still hold. | M |
| FR-R7 | Healing never edits expectations. A FAIL never produces a heal proposal. | M |
| FR-R8 | Applying a proposal requires an explicit command. | M |
| FR-R9 | Response-side drift that would need an expectation change produces an expectation-change request for human review, never a heal. | M |

### Verification integrity (AI-era)
| ID | Requirement | P |
|---|---|---|
| FR-V1 | Tests, expectations, traces, and proposals carry provenance (author kind: human, tool, agent; approver; timestamp), stamped by the core. | M |
| FR-V2 | Only a human identity can approve. Agent and tool identities can only propose. | M |
| FR-V3 | Review flags any change that loosens, removes, skips, or quarantines an expectation or test as a separate item (`expectation.weakened` event). | M |
| FR-V4 | Optional held-out acceptance suite that agent sessions cannot read or modify. | S |
| FR-V5 | `strength` command runs the suite against plugin-provided seeded faults and reports suite strength per suite and per change. | S |
| FR-V6 | A model may attach advisory evidence (e.g. LLM-judge score) but never decides an outcome. | M |

### Agent interface
| ID | Requirement | P |
|---|---|---|
| FR-G1 | Structured API exposing impact, run, explain, propose, status with machine-readable results. | M |
| FR-G2 | MCP server over the same API. | S |
| FR-G3 | Role-based permissions for agent sessions (run, explain, propose; never approve or edit expectations). | M |
| FR-G4 | Every agent action is recorded as an event with provenance. | M |

### Skipping and impact
| ID | Requirement | P |
|---|---|---|
| FR-S1 | CACHED-PASS only when all conditions in `plan.md` section 9 hold. | M |
| FR-S2 | If no version probe is configured, skipping is disabled. | M |
| FR-S3 | Every CACHED-PASS records the evidence: which fingerprints matched and from which prior run. | M |
| FR-S4 | Sampled re-verification with a configurable rate; disagreements are logged as false skips. | M |
| FR-S5 | Tests flagged non-hermetic are never skipped. | M |
| FR-S6 | Map tests to what they touch (operations, routes, components, files); `--changed` and `impact` select tests affected by a spec or code diff. Works without a version probe. | M |

### Observability and reporting
| ID | Requirement | P |
|---|---|---|
| FR-O1 | Run view: outcomes, durations, and the reason for every skip and drift. | M |
| FR-O2 | Test view: definition, trace, recent evidence, outcome history. | M |
| FR-O3 | Change view: what changed since the last verified run and which tests it affects. | M |
| FR-O4 | Health view: cache-hit rate, drift rate, flaky tests, time saved, false-skip rate. | S |
| FR-O5 | Export JUnit XML; generate static HTML reports. | M |
| FR-O6 | Event store is queryable with plain SQL. | M |
| FR-O7 | Any outcome can be explained from stored artifacts alone (no live system needed). | M |

### Benchmark
| ID | Requirement | P |
|---|---|---|
| FR-B1 | Reference target API with switchable seeded changes (contract changes, behavioral bugs, benign changes). | M |
| FR-B2 | Equivalent suites for cairn-test, Postman/Newman, and REST Assured. | M |
| FR-B3 | Scoring script for create effort, maintenance effort, accuracy, and speed. | M |
| FR-B4 | Reproducible runs: seeded changes applied from a script, results written to a machine-readable file. | M |
| FR-B5 | Optional comparison against Keploy (record-and-replay prior art), reported separately from the required comparators. | C |
| FR-B6 | Integrity benchmark: a scripted agent tries to turn failing tests green (weaken, skip, edit traces); report how many attempts are blocked or flagged. | M |
| FR-B7 | Optional context comparators: Hurl or Step CI, Schemathesis, Playwright Test Agents. | C |

## 3. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 | Strict replay needs no network access to any model and no model runtime installed. |
| NFR-2 | Replay overhead per step (excluding the HTTP call) under 5 ms on a laptop. |
| NFR-3 | Planning 1,000 tests with trace and fingerprint comparison under 2 seconds. |
| NFR-4 | All persistent formats are versioned (`schema:` field) and validated by published JSON Schemas. |
| NFR-5 | Secrets are never written to traces, events, or reports (masking by configured names and patterns). |
| NFR-6 | Deterministic: the same inputs and system state produce the same outcomes and the same ordering in reports. |
| NFR-7 | Human-readable files: diffs of tests and traces are meaningful in a pull request. |
| NFR-8 | Core has no dependency on HTTP, browser, or model libraries. |
| NFR-9 | Core logic is unit-testable using only the fake plugin. |
| NFR-10 | Provenance and approval records cannot be modified through the plugin or agent interfaces. |

## 4. Acceptance criteria for v1

A test passes a requirement only if the evidence can be shown, not asserted.

1. **Authoring**: starting from an OpenAPI spec, a user gets N trusted passing tests without writing code, and the time is recorded.
2. **Determinism**: strict replay of a recorded suite gives identical outcomes across 10 consecutive runs against a stable target.
3. **Outcome separation**: in the benchmark, contract changes yield DRIFT (never FAIL; expectations that cannot apply are `unevaluable`), behavioral bugs yield FAIL (never DRIFT or PASS), benign changes yield PASS.
4. **No false heals**: across all seeded bugs, zero heal proposals alter an expectation or convert a FAIL into a PASS.
5. **Skip safety**: with a version probe, false-skip rate on seeded changes is measured and reported; target at or near zero. Without a probe, no test is skipped.
6. **Explainability**: for any outcome in a run, the report shows why (including each skip) using stored artifacts only.
7. **Extensibility**: a second, structurally different step type is added using only the plugin contracts, with no core changes (a CLI-command step is sufficient).
8. **Comparative result**: the benchmark report compares cairn-test with Newman and REST Assured on all metrics and states where it does not win.
9. **Integrity**: in the integrity benchmark, every attempt by an agent identity to weaken, remove, or approve an expectation is blocked or flagged.
10. **Agent use**: a coding agent can run impact analysis, execute affected tests, and get an explanation of each outcome through the agent interface without CLI scraping.

## 5. Out of scope

UI and mobile plugins (paper design only in v1), explore mode, hosted dashboards, model-approved expectations, load and performance testing, multi-user workflows, GraphQL/gRPC (design the contracts so they could be added).

## 6. Assumptions and dependencies

- The system under test provides an OpenAPI 3 spec, or one can be produced.
- The system under test exposes some version indicator for skip eligibility. If not, skipping stays off.
- Test environments allow isolated data per worker, or tests declare themselves non-hermetic.
- A local model backend is optional and only needed for `intent` steps and draft generation.