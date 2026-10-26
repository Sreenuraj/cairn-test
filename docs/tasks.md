# cairn-test Tasks

Companion to `plan.md`, `requirements.md`, and `core-vision.md`. Each task lists the requirement IDs it satisfies and a done-check. Work phases in order; tasks inside a phase can be parallelized unless noted.

Legend: `[ ]` todo, `[~]` in progress, `[x]` done.

## Phase 0: Specification (no engine code)

Goal: freeze the contracts before building on them. They are the hardest thing to change later.

- [ ] **T0.1 JSON Schemas** for `cairn-test.test/v1`, `cairn-test.trace/v1`, event records, result records, proposals, including `provenance` fields. (FR-C1, FR-C2, NFR-4, FR-V1)
  Done when: schemas validate the examples in `plan.md`, and invalid examples are rejected with useful messages.
- [ ] **T0.2 Plugin contract definitions** as interface definitions plus doc comments. (FR-P1, FR-P2)
  Done when: a short doc explains each contract with inputs, outputs, and what the plugin must never do.
- [ ] **T0.3 Outcome rules spec** as a decision table, including precedence, every invariant, `unevaluable` expectations, observation diff classes (identical / additive / breaking), and statistical expectations. (FR-C5, FR-C6, FR-C13, FR-C14)
  Done when: the table is a test fixture (input conditions to expected outcome) the engine will later be tested against, and it covers "renamed asserted field gives DRIFT, not FAIL".
- [ ] **T0.4 Paper design of a UI plugin** (sessions, waits, nondeterminism, accessibility-tree observation, visual evidence) and a CLI-command step, to stress the contracts. (FR-P3, FR-P5)
  Done when: both can be written with the contracts as drafted, no HTTP vocabulary leaks into the core, and a UI Observation with additive-vs-breaking rules is defined.
- [ ] **T0.4b Observation model**: core definition of Observation and ObservationDiff, filled in per plugin. (FR-C14)
- [ ] **T0.4c Provenance and permission model**: identities (human, tool, agent), roles, what each can do, what counts as weakening. (FR-V1, FR-V2, FR-V3, FR-G3)
- [ ] **T0.5 Fingerprint input list** finalized, with the version-probe options. (FR-S1, FR-S2, FR-A9)
- [ ] **T0.6 Decide implementation language.** (plan.md section 17; name and file conventions are settled: see plan.md section 7)

**Gate G0**: contracts and schemas reviewed by you. Do not start Phase 1 before this.

## Phase 1: Core with a fake plugin

Goal: a working engine with no real domain. Every outcome must be producible.

- [ ] **T1.1 Project skeleton**, config loading, logging. (NFR-8)
- [ ] **T1.2 Loaders and validators** for tests, traces, config, env profiles. (FR-C1, FR-C2)
- [ ] **T1.3 Event bus and stores**: JSONL writer, SQLite schema, artifact store. (FR-C7, FR-C8, FR-O6)
- [ ] **T1.4 Plugin registry** and wrapper that calls plugins and emits events. (FR-P2, FR-P3)
- [ ] **T1.5 Outcome engine** implementing the decision table from T0.3. (FR-C5, FR-C6)
  Done when: the T0.3 fixture passes completely.
- [ ] **T1.6 Planner**: selection, EXECUTE/SKIP decision with reason, fingerprint comparison. (FR-C3, FR-C11)
- [ ] **T1.7 Scheduler and workers** with isolation, parallelism, timeouts. (FR-C4, FR-C12)
- [ ] **T1.8 Fake plugin** that can script each outcome (pass, fail, drift, error) deterministically. (FR-C10)
- [ ] **T1.9 CLI core**: `run` with strict mode and a basic text report. (FR-C9)
- [ ] **T1.10 Core unit tests** using only the fake plugin. (NFR-9)
- [ ] **T1.11 Provenance stamping and approval guard**: only human identities approve; plugins and agents cannot alter provenance. (FR-V1, FR-V2, NFR-10)
- [ ] **T1.12 Weakening detector**: diff tests and expectations, emit `expectation.weakened`, surface in review. (FR-V3)
- [ ] **T1.13 Fixtures, setup/teardown, parameterization, sessions** in the core. (FR-C16)

**Gate G1**: the engine runs a mixed suite on the fake plugin and every outcome (including DRIFT with `unevaluable` expectations) appears with a correct explanation in the stored events.

## Phase 1b: Agent interface

- [ ] **T1b.1 Structured API**: impact, run, explain, propose, status with machine-readable results. (FR-G1)
- [ ] **T1b.2 Agent roles and permissions** enforced at the API boundary. (FR-G3)
- [ ] **T1b.3 Agent action events** with provenance. (FR-G4)
- [ ] **T1b.4 MCP server** over the API. (FR-G2)

**Gate G1b**: a coding agent can run, explain, and propose through MCP on the fake plugin, and every attempt to approve or edit an expectation is refused and logged.

## Phase 2: API plugin (execution and assertions)

- [ ] **T2.1 OpenAPI ingestion** and normalized operation hashing, including `$ref` resolution. (FR-A1)
- [ ] **T2.2 HTTP step executor**: templating, variable binding, JSONPath extraction. (FR-A2)
- [ ] **T2.3 Auth helpers** (bearer, basic, API key, login-and-extract), with secret masking. (FR-A6, NFR-5)
- [ ] **T2.4 Assertion types**: status, header, jsonpath, schema-from-spec, follow-up state. (FR-A3)
- [ ] **T2.5 API Observer**: record response contract (status, schema, header names) and classify diffs as identical / additive / breaking; mark expectations `unevaluable` when the diff explains it. (FR-A4, FR-A5, FR-C13, FR-C14)
- [ ] **T2.6 Version probe** implementations (header, endpoint, build id). (FR-A9)
- [ ] **T2.7 Evidence collector** for requests and responses with masking. (FR-C8)
- [ ] **T2.8 Plugin tests** against a local mock server, then against the reference API from Phase 6 when available.

**Gate G2**: hand-written explicit-`op` tests execute against a real API and produce correct PASS, FAIL, and DRIFT.

## Phase 3: Record, review, and heal

- [ ] **T3.1 `init --spec`**: project scaffold and spec import. (FR-R1)
- [ ] **T3.2 Trace writer** and plain-language rendering of each step. (FR-R4)
- [ ] **T3.3 Approval flow**: stamp who and when; traces only change through it. (FR-R5, FR-R8)
- [ ] **T3.4 Strict replay from traces**, with pre-fingerprint check and post-contract check. (FR-C9, FR-A5)
- [ ] **T3.5 Heal proposals**: file format, diff rendering, which expectations still hold. (FR-R6)
- [ ] **T3.6 Enforce healing limits**: never touch expectations; no proposal on FAIL; response-side drift produces an expectation-change request instead. (FR-R7, FR-R9)
  Done when: an automated test tries to make healing change an expectation, and the engine refuses.
- [ ] **T3.7 Model backend interface** with two implementations: none, and local (e.g. Ollama). (FR-A7)
- [ ] **T3.8 Intent resolver** constrained to spec operations; resolution is recorded in the trace as `resolved_by`. (FR-A7)
- [ ] **T3.9 Draft generator** from the spec into `proposals/`, plus `review` flow. (FR-A8, FR-R2, FR-R3)

**Gate G3**: starting from a spec, you can go draft, review, record, strict replay with no code written.

## Phase 4: Impact, verification strength, skip logic, and scale

- [ ] **T4.0 Impact map and change-based selection** from spec and code diffs (`impact`, `--changed`). Do this before skip caching. (FR-S6)
- [ ] **T4.0b Suite strength**: FaultSeeder for the API plugin and `strength` command. (FR-V5)
- [ ] **T4.0c Richer expectation kinds**: property, metamorphic, differential, statistical. (FR-C15, FR-V6)
- [ ] **T4.0d Held-out acceptance suite** support. (FR-V4)
- [ ] **T4.1 Skip evaluator** (later optimization) implementing all conditions in plan.md section 9. (FR-S1, FR-S2)
- [ ] **T4.2 CACHED-PASS evidence records** and report rendering. (FR-S3)
- [ ] **T4.3 Sampled re-verification** and false-skip tracking. (FR-S4)
- [ ] **T4.4 Non-hermetic flag** and exclusion from skipping. (FR-S5)
- [ ] **T4.6 Flakiness tracking and quarantine** from history, feeding skip eligibility. (FR-C17)
- [ ] **T4.7 Performance pass**: meet NFR-2 and NFR-3 with measurements recorded.

**Gate G4**: seeded contract changes in the benchmark target cause exactly the affected tests to be selected (via the impact map), unaffected tests are CACHED-PASS with evidence when a probe is configured, and suite strength is reported.

## Phase 5: Reporting and observability

- [ ] **T5.1 Run view** (HTML + terminal). (FR-O1)
- [ ] **T5.2 Test view** with trace, evidence, and history. (FR-O2)
- [ ] **T5.3 Change view** (`diff`). (FR-O3)
- [ ] **T5.4 Health view** with false-skip rate and time saved. (FR-O4)
- [ ] **T5.5 JUnit XML export.** (FR-O5)
- [ ] **T5.6 Explainability check**: for a sample run, answer "why was this outcome given?" using only stored artifacts. (FR-O7)

**Gate G5**: a fresh checkout with only the stored artifacts can regenerate every report.

## Phase 6: Benchmark harness

Can start in parallel with Phase 2 for the target API and competitor suites.

- [ ] **T6.1 Reference target API** (~15 endpoints, stateful: auth, products, orders, payments, refunds), with a spec. (FR-B1)
- [ ] **T6.2 Seeded changes** as switchable flags: contract changes, behavioral bugs, benign changes, each with an expected outcome label. (FR-B1)
- [ ] **T6.3 Equivalent Newman suite.** (FR-B2)
- [ ] **T6.4 Equivalent REST Assured suite.** (FR-B2)
- [ ] **T6.5 cairn-test suite** (drafted from the spec, then reviewed). (FR-B2)
- [ ] **T6.5b (optional) Keploy comparison**: record the same flows with Keploy and score it on the same metrics. (FR-B5)
- [ ] **T6.5c Integrity benchmark**: scripted agent attempts to weaken, skip, or approve its way to green; score blocked/flagged attempts. (FR-B6)
- [ ] **T6.5d (optional) Context comparators**: Hurl or Step CI, Schemathesis, Playwright Test Agents. (FR-B7)
- [ ] **T6.6 Scoring script**: create effort, maintenance effort, accuracy (caught, false failures, false heals, false skips), speed (full and incremental). (FR-B3)
- [ ] **T6.7 Reproducible run script** writing machine-readable results. (FR-B4)

Measure effort honestly: log wall-clock time and authored lines for each tool, doing the maintenance steps by hand for the competitors.

## Phase 7: Evaluation and decision

- [ ] **T7.1 Run the full benchmark** at least 3 times; record variance.
- [ ] **T7.2 Check acceptance criteria 1 to 10** in requirements.md section 4, with evidence links.
- [ ] **T7.3 Second plugin proof**: implement the CLI-command step using only the contracts. (Acceptance 7)
- [ ] **T7.4 Write the comparison report**: where it wins, where it ties, where it loses.
- [ ] **T7.5 Go/no-go decision** on extending to UI.

**Gate G7 (go/no-go)**
- Go to UI if: zero false heals, correct DRIFT/FAIL/PASS separation, all integrity attacks blocked or flagged, clear maintenance advantage, and the second plugin needed no core changes.
- Revisit design if: false heals or false skips appear that the fingerprint inputs can't explain, or the advantage disappears once review effort is counted.

## Suggested order of work

1. Phase 0 (spec) then G0.
2. Phase 1 and the benchmark target API (T6.1, T6.2) in parallel.
3. Phase 1b (agent interface), then Phase 2, then Phase 3, then G3.
4. Phase 4, then Phase 5.
5. Remaining benchmark suites and Phase 7.

## Notes for implementation

- Build the decision table (T0.3) first and treat it as the test oracle for the outcome engine.
- Keep core imports free of HTTP, browser, and model libraries; enforce with a lint rule or import test (NFR-8).
- Never log secrets; add a test that scans traces, events, and reports for configured secret values (NFR-5).
- Prefer explicit `op` steps for anything critical. Treat `intent` steps as a convenience layer that records an `op` underneath.
- No inline scripts in test files. The only escape hatch for hard cases is a typed step or assertion plugin.
- Never let a model decide an outcome; LLM-judge output is advisory evidence only.
- When a design question comes up mid-build, update `plan.md` first, then change code, so the plan stays the source of truth.