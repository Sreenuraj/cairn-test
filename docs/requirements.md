# cairn-test Requirements (v1.2)

Companion to `plan.md` (design, source of truth) and `core-vision.md` (rationale and scope decisions). IDs are stable so tasks and tests can reference them. IDs that existed in v1 and were removed or deferred are listed in section 7.

Priority: **M** = must for v1, **S** = should, **C** = could. Rule: **no gate or acceptance criterion depends on an S or C item.**

## 1. Users, thesis, and constraints

- Primary user: the author, running locally and in CI. No servers, accounts, or hosted components.
- Secondary user: coding agents acting in the same repository, through the CLI's JSON output (and later MCP). Agents are untrusted (threat model: `plan.md` section 10).
- Everything that defines a test or its execution is a file in git. Approvals are signed files in git; the trust root lives outside the repository (a CI variable for enforcement).
- No model is used anywhere in v1.
- **v1 thesis:** correct DRIFT/FAIL/PASS classification, including compound cases, and lower maintenance effort including review time, compared with an LLM-assisted Newman suite. The maintenance advantage is expected mainly from **triage** (structured DRIFT reports), then impact selection, then deterministic repair (`plan.md` section 1).

## 2. Functional requirements

### Core engine
| ID | Requirement | P |
|---|---|---|
| FR-C1 | Load test definitions (`cairn-test.test/v1`) and validate them against a JSON Schema with clear errors. | M |
| FR-C2 | Load and validate traces, approvals, and proposals; reject unknown schema versions with a migration hint. | M |
| FR-C3 | Plan each test as EXECUTE or SKIPPED (filter, tag, quarantine), recording the reason. | M |
| FR-C4 | Execute tests in isolated workers with configurable parallelism. | M |
| FR-C5 | Assign outcomes only in the outcome engine, following ERROR > FAIL > DRIFT > PASS, and report lower findings as detail. | M |
| FR-C6 | Support outcomes PASS, FAIL, DRIFT, ERROR, SKIPPED with the meanings in `plan.md` 6.1. | M |
| FR-C7 | Emit structured events for every lifecycle stage; persist to JSONL and SQLite. | M |
| FR-C8 | Store masked evidence per step, linked to events. | M |
| FR-C9 | Modes: strict, dev, record, heal, with the behavior in `plan.md` section 5. | M |
| FR-C10 | A fake plugin can drive the full lifecycle and produce every outcome, every expectation value, and every compound case in `plan.md` 6.3. | M |
| FR-C11 | Selection by tag and id. | M |
| FR-C12 | Configurable per-test timeout and per-run budget. | S |
| FR-C13 | Expectation values `true`, `false`, `unevaluable` decided by the core per `plan.md` 6.2, using each assertion's declared `reads` paths and the observation diff. | M |
| FR-C14 | Blocked steps: a step that cannot run because a required variable is missing gets `blocked-by:<step>`; its expectations are `unevaluable`; the test outcome follows the blocking step's cause. | M |
| FR-C15 | Observation diffs classify each change as identical, additive, or breaking, with paths; only breaking changes drive DRIFT. | M |
| FR-C16 | Additive diffs never silently update recorded observations; `accept-observations` creates a proposal that needs approval. | M |
| FR-C17 | Fixtures (setup and teardown steps as data) and parameterized tests (a data table that expands into cases). | S |
| FR-C18 | Per-worker data isolation built-ins (`{run.uid}`, `{worker.id}`); `hermetic: false` tests run serially. | M |
| FR-C19 | Quarantine: a quarantined test is SKIPPED with a reason; quarantine is an edit that needs approval. | S |
| FR-C20 | Strict-mode guards: missing trace, environment-profile mismatch, or unapproved/tampered content is ERROR with a specific reason code. | M |

### Plugin contracts
| ID | Requirement | P |
|---|---|---|
| FR-P1 | Language-neutral contracts for StepExecutor, Observer, Fingerprinter, AssertionType (with `reads`), Healer, EvidenceCollector, and optional SessionProvider. | M |
| FR-P2 | Plugins return data only; the core wraps all calls, emits events, and decides outcomes. | M |
| FR-P3 | New step types and assertion types can be added without modifying core code. | M |
| FR-P4 | Plugin and framework versions are recorded in every result. | M |
| FR-P5 | A UI plugin paper sketch lists the contract pressures (sessions, waits, nondeterminism, visual evidence) and open questions; it does not freeze UI rules. | M |

### API plugin
| ID | Requirement | P |
|---|---|---|
| FR-A1 | Ingest OpenAPI 3.0/3.1; normalized per-operation hashes including referenced schemas. | M |
| FR-A2 | HTTP steps with explicit `op`, variable binding, JSONPath extraction, header and body templating. JSON bodies; status-only checks for other content types. | M |
| FR-A3 | Assertions: status, header, jsonpath (equals, matches, exists, in, range), schema from spec, follow-up state operation. Each declares `reads`. | M |
| FR-A4 | Observer records status, header names, and normalized body shape. | M |
| FR-A5 | Response diff rules exactly as in `plan.md` section 14, with a fixture per rule. | M |
| FR-A6 | Auth helpers: bearer, basic, API key, login-and-extract. | M |
| FR-A7 | Spec-diff classifier for the request side (path, method, parameter added, removed, or moved; required vs optional; enum changes). | M |
| FR-A8 | Deterministic draft generator from the spec (status, schema, required-field negatives, auth variants) into `proposals/`. | S |
| FR-A9 | `property` assertion using CEL. | S |

### Record, review, approval, and healing
| ID | Requirement | P |
|---|---|---|
| FR-R1 | `init` creates a project from an OpenAPI spec. | M |
| FR-R2 | `record` executes explicit-`op` steps and writes traces as proposals with a plain-language rendering. | M |
| FR-R3 | `review` shows proposals and diffs of approved files with labels (`expectation-removed`, `operator-loosened`, `scope-changed`, `binding-changed`, `quarantined`). | M |
| FR-R4 | `approve` writes an approval covering content hashes of the test, trace, referenced data and fixtures, config, and project-local plugin source, signed with an SSH key (`ssh-keygen -Y sign`). | M |
| FR-R5 | Heal proposals only for healable fields (`plan.md` section 11), containing old and new resolved step, the spec diff, and which expectations still evaluate `true` in a dry run. | M |
| FR-R6 | A new required parameter produces a value request, never an invented value. A renamed or removed asserted field produces an expectation-change request, never a heal. | M |
| FR-R6a | Rename and move suggestions: when the spec diff shows exactly one same-type candidate for a removed asserted field (same object or nested), the expectation-change request carries a suggested JSONPath rewrite. It never changes the expected value or operator. With zero or several candidates, there is no suggestion. | M |
| FR-R6b | OperationId rename with identical method, path, and schemas produces a heal proposal mapping the old id to the new one. | M |
| FR-R7 | No heal proposal or suggestion for a FAIL. Healing never changes expectations, data values, args, or test files (enforced by test). | M |
| FR-R8 | Applying any proposal requires `approve` (a new signature). | M |

### Verification integrity
| ID | Requirement | P |
|---|---|---|
| FR-V1 | Strict mode verifies, before running, that every file a test depends on (test, trace, data, fixtures, config, project-local plugin source) matches a hash in an approval whose signature verifies against the trust root; otherwise ERROR (`unapproved`, `tampered`, `bad-signature`, `unknown-signer`). | M |
| FR-V2 | The trust root is read from outside the repository: `CAIRN_ALLOWED_SIGNERS` in CI, user config locally. Repo config cannot change it or disable verification. Strict mode has no bypass flag. | M |
| FR-V3 | Identity is established only by signature; author names and kinds are labels. | M |
| FR-V4 | `doctor` reports the checkable assumptions: signing key type (warn unless security-key or Secure Enclave), trust-root source (warn when local), and whether the CI workflow pins the engine. | S |
| FR-V5 | Tamper suite: automated tests that edit an expectation, loosen an operator, delete a test or step, change a data binding, quarantine a test, edit a trace, edit config, edit a project-local plugin, forge an approval, or replay an old approval against new content; strict mode must reject every case. | M |
| FR-V6 | `approve` prints the subject, labels, and covered files before requesting a signature, and records the key type in the approval. | M |
| FR-V7 | `verify` checks all approvals without running tests, for use as the first CI step. | M |
| FR-V8 | Reference CI workflow (GitHub Actions) that pins the engine by digest or hash, reads the trust root from a CI variable, runs `verify` then `run --strict`, plus documented repository settings (ruleset on `main`, agent token without workflow permission). | S |

### Selection and impact
| ID | Requirement | P |
|---|---|---|
| FR-S1 | Map tests to touched operations; `impact --spec-diff` lists affected tests with reasons; `run --changed` runs them. | M |
| FR-S2 | Optional declared `touches` mappings in test files. | C |

### Agent and machine interface
| ID | Requirement | P |
|---|---|---|
| FR-G1 | Every command supports `--json` with a published schema and stable exit codes. | M |
| FR-G2 | `explain <run> <test>` returns a structured explanation from stored artifacts. | M |
| FR-G3 | MCP server exposing run, explain, impact, status, and propose over the same internal API. | S |

### Observability and reporting
| ID | Requirement | P |
|---|---|---|
| FR-O1 | Run view: outcomes, durations, reasons for every skip, drift, and unevaluable or blocked expectation. | M |
| FR-O2 | Test view: definition, trace, recent evidence, outcome history. | M |
| FR-O3 | Change view: spec diff, affected tests, proposals. | M |
| FR-O4 | Health view: drift rate, flaky tests, quarantine list. | S |
| FR-O5 | JUnit XML export; static HTML reports. | M |
| FR-O6 | Event store is queryable with plain SQL. | M |
| FR-O7 | Any outcome can be explained from stored artifacts alone. | M |

### Migration
| ID | Requirement | P |
|---|---|---|
| FR-M1 | `migrate` upgrades stored files between schema versions and reports what changed. Required from the first schema bump; v1 ships the command and the framework. | M |

### Benchmark
| ID | Requirement | P |
|---|---|---|
| FR-B1 | Reference target API (about 12 endpoints, stateful) with switchable seeded changes: contract, behavioral, benign, and compound, each labeled with the expected outcome per test. | M |
| FR-B2 | Behavior catalog of N = 30 behaviors, implemented in cairn-test and Newman; REST Assured as a should. | M |
| FR-B3 | All suites built and maintained LLM-assisted with the same assistant; wall-clock time, authored lines, and review time are logged per task. During maintenance every tool gets the same inputs (failing output and spec diff). | M |
| FR-B4 | Scoring script: classification confusion matrix, triage time and fix time (both including review), false heals, masking suggestions, heal and suggestion acceptance rates, create effort, speed. | M |
| FR-B8 | Pre-registration: behaviors, the 12-behavior core subset, seeded changes with expected outcome and mechanism, metrics, analysis, and success/kill thresholds are committed under a signed tag before any suite is written, and never edited. Deviations are logged and results reported against both versions. | M |
| FR-B5 | Reproducible runs: seeded changes applied from a script; results written to a machine-readable file. | M |
| FR-B9 | Suites are frozen under a signed tag before any seeded change is enabled; later suite edits count as maintenance work. | M |
| FR-B6 | REST Assured suite. | S |
| FR-B7 | Keploy comparison as context. | C |

## 3. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 | No model, model runtime, or network access other than to the system under test is needed for any v1 command. |
| NFR-2 | Replay overhead per step (excluding the HTTP call): target under 5 ms. A provisional target; T2.9 measures the baseline and confirms or revises it. |
| NFR-3 | Planning plus approval verification for 1,000 tests: target under 2 s. Same provisional status as NFR-2. |
| NFR-4 | All persistent formats carry a `schema:` version and are validated by published JSON Schemas. |
| NFR-5 | Secrets and configured PII fields are never written to traces, evidence, events, or reports (masking by name and pattern), verified by a scanning test. |
| NFR-6 | Deterministic: the same inputs and system state give the same outcomes and report ordering. |
| NFR-7 | Human-readable files; diffs of tests, traces, and approvals are meaningful in a pull request. |
| NFR-8 | Core has no dependency on HTTP, browser, or model libraries (enforced by an import test). |
| NFR-9 | Core logic is unit-testable using only the fake plugin. |

## 4. Acceptance criteria for v1

A criterion passes only with evidence (artifacts, logs, benchmark output).

1. **Authoring without code**: from an OpenAPI spec, the 30 catalog behaviors are expressed as YAML tests with explicit `op` steps, recorded, reviewed, approved, and passing, with no test code. Time is logged, including review.
2. **Determinism**: strict replay of the approved suite gives identical outcomes and report ordering across 10 consecutive runs against a stable target.
3. **Classification**: across all seeded changes, every test's outcome matches its expected label, including the compound cases in `plan.md` 6.3. In particular: contract-only changes are DRIFT and never FAIL; bug-only changes are FAIL and never DRIFT or PASS; benign changes are PASS; contract change plus bug is FAIL with drift detail.
4. **No false repairs**: zero false heals and zero masking suggestions (formal definitions, `plan.md` section 11) across all seeded changes.
5. **Maintenance**: median triage time after contract changes, including review, is lower for cairn-test than for the LLM-assisted Newman suite by at least the pre-registered threshold, and median total time to green is not higher. Numbers and variance are reported, including where fix time alone does not win.
6. **Explainability**: for every outcome in a benchmark run, `explain` produces the reason from stored artifacts only.
7. **Extensibility**: a CLI-command step type is added using only the plugin contracts, with no core changes.
8. **Integrity**: every case in the tamper suite (FR-V5) is rejected by strict mode.
9. **Honest report**: the benchmark report states where cairn-test does not win (expected: create effort, raw speed, uncovered bugs, spec-diff selection, fix time on simple request-side changes) and lists every pre-registration deviation.

## 5. Out of scope for v1

See `plan.md` section 16. Summary: skip caching, models and intent steps, explore mode, held-out suites, statistical and differential expectations, fault-seeding suite strength, code-diff selection, UI and mobile plugins (paper sketch only), non-JSON bodies, GraphQL/gRPC, pytest/Playwright adapters, hosted or multi-user features, load testing.

## 6. Assumptions and dependencies

- The system under test provides an OpenAPI 3.0/3.1 spec, or one can be produced.
- Test environments allow per-worker isolated data, or tests declare `hermetic: false`.
- Humans approve with an SSH key that needs a physical action per signature: a FIDO2 `ed25519-sk` key (recommended) or a Secure Enclave key with Touch ID. A passphrase-protected key file never loaded into an ssh-agent is tolerated with a warning. Keys usable without a human action are unsupported (`plan.md` 10.2).
- The agent runs as the same OS user and can modify anything local, including the installed engine and the local trust root. Local verification is advisory.
- Enforcement happens in CI: a pinned engine, the trust root in a CI variable, and an agent git credential with no workflow permission and no ability to push to `main` (`plan.md` 10.3).
- OpenSSH 8.2+ is available for `ssh-keygen -Y sign/verify`.

## 7. Changes from v1

| v1 ID | Status in v1.1 |
|---|---|
| FR-C9 modes | Now strict, dev, record, heal (no model). |
| FR-C11 `--changed` | Moved to FR-S1 (spec diff only). |
| FR-C13 to C17 (v1) | Rewritten as FR-C13 to C20 with defined semantics. |
| FR-A7 intent resolution | Deferred (post-v1). The ID is reused for the request-side spec-diff classifier. |
| FR-A8 drafting | Kept as S, deterministic only; no gate depends on it. |
| FR-A9 version probe | Deferred with skip caching. ID reused for the CEL `property` assertion. |
| FR-S1 to S5 skip caching | Deferred (post-v1); design preserved in `plan.md` appendix A. |
| FR-S6 impact map | Now FR-S1, spec diff only. |
| FR-V1 to V6 (v1) | Replaced by signature-based approvals (FR-R4, FR-V1 to V5). Held-out suites and suite strength deferred. |
| FR-G1 to G4 (v1) | Replaced by FR-G1 to G3; agent permissions are enforced by signatures, not by interface roles. |
| FR-B6 (v1) scripted agent | Replaced by the tamper suite (FR-V5) as a correctness test, not a benchmark claim. |
| Acceptance 10 agent use | Covered by FR-G1 and FR-G2; MCP is S. |
| (v1.2) | Added FR-R6a, FR-R6b, FR-V6 to V8, FR-B8, FR-B9; tightened FR-R4, FR-V1, V2, V4, V5, FR-B3, B4, and acceptance 4, 5, and 9. |