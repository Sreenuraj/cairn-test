# cairn-test Tasks (v1.2)

Companion to `plan.md`, `requirements.md`, and `core-vision.md`. Each task lists the requirement IDs it satisfies and a done-check. Phases run in order unless noted; tasks inside a phase can run in parallel unless noted.

Rules:
- Gates depend only on **M** requirements. S and C tasks are marked *(S)* or *(C)* and never block a gate.
- A task only depends on tasks in its own phase or earlier ones.

Legend: `[ ]` todo, `[~]` in progress, `[x]` done.

## Timebox, checkpoints, and kill criteria

E1 is kept deliberately small. **Signing, approvals, strict mode, and the tamper suite are not in E1** (they are the likeliest overrun and don't test the thesis). E1 uses the 12-behavior core subset, not all 30.

| Checkpoint | Scope | Budget | Hard stop |
|---|---|---|---|
| **E1: classification** | Phase 0, Phase 1, Phase 2, and T6.1, T6.2 for the 12-behavior core subset. Tests are hand-written YAML run in dev mode. | 4 weeks | 6 weeks |
| **E2: maintenance** | Phase 3 (approvals, strict, tamper suite), Phase 4 (healing, suggestions, impact), all 30 behaviors, the Newman suite, and the scoring script | 5 weeks | 7 weeks |
| **v1 complete** | Phases 5–7 | 3 weeks | 4 weeks |

### E1 kill criteria (decided now, recorded in the pre-registration)

Run the pre-registered seeded changes against the 12-behavior subset.

- **Continue** if every case matches its label: contract-only, bug-only, benign, and all compound cases.
- **Stop and rethink the outcome model** if *any* compound case misclassifies and the fix would need one of these:
  - a per-test or per-assertion special case;
  - a rule outside `plan.md` 6.2 and 6.3;
  - knowledge an observation cannot carry (e.g. the meaning of a field rather than its shape).

  In that case, write `docs/e1-postmortem.md` before changing anything.
- **Fix and re-run once** if misclassifications are implementation bugs that the existing rules already cover. A second failed run means stop.
- **Stop** if a benign change (new optional field, reordered fields, timestamps) produces DRIFT that the additive rules can't express.

### Fallback if E1 slips

At week 4, if E1 is not done:
1. Cut T0.7 (UI paper sketch) to a one-page list of open questions.
2. Replace the OpenAPI ingestion work with a minimal subset: no `oneOf`/`allOf`, local `$ref` only.
3. Run E1 against a 6-behavior subset, keeping every compound case. Classification is the thing being tested, not breadth.

At week 6 (hard stop): run whatever classifies today against the compound cases and make the go/no-go call on that evidence. Do not extend E1 again.

### E2 kill criteria

- **Stop** if median *triage* time (review included) is not lower than Newman's by at least the pre-registered threshold (default: 30%) on the first full run. Fix-time wins alone do not rescue the thesis.
- **Stop** if any false heal or masking suggestion occurs that the section 11 rules can't prevent.
- **Descope, don't stop,** if the tamper suite overruns: ship approvals and strict mode with the cases done, mark the rest as known gaps, and keep acceptance 8 open.

If a checkpoint fails, write down why before changing the design.

## Phase 0: Specification (no engine code)

- [ ] **T0.1 Decide the implementation language.** Default: Python 3.12 (JSON Schema, CEL, and OpenAPI libraries are mature; contracts stay JSON-Schema-first). (plan.md section 4)
- [ ] **T0.2 JSON Schemas** for test, trace, approval, proposal, event, and result records. (FR-C1, FR-C2, NFR-4)
  Done when: the examples in `plan.md` validate, and a set of invalid examples is rejected with useful messages.
- [ ] **T0.3 Plugin contract definitions** with doc comments: inputs, outputs, what a plugin must never do. (FR-P1, FR-P2)
- [ ] **T0.4 Outcome decision table** as a fixture file: outcomes, precedence, expectation values (`true`, `false`, `unevaluable`, blocked), and every compound case in `plan.md` 6.3. (FR-C5, FR-C6, FR-C13, FR-C14)
  Done when: each row has input conditions and an expected outcome, ready to be used as the outcome engine's test oracle.
- [ ] **T0.5 Observation and diff rules** for the API plugin as fixtures: one recorded/observed pair per rule in `plan.md` section 14, response and request side. (FR-C15, FR-A5, FR-A7)
- [ ] **T0.6 Approval specification**: canonical serialization, what `covers` must include, signature namespace, trust-root lookup order, reason codes (`unapproved`, `tampered`, `bad-signature`, `unknown-signer`). (FR-R4, FR-V1, FR-V2)
- [ ] **T0.7 UI plugin paper sketch**: list the pressures on each contract (sessions, waits, nondeterminism, observation shape, visual evidence) and the open questions. (FR-P5)
  Done when: the sketch exists and either confirms the contracts or lists concrete contract changes. It does not need to settle UI diff rules.
- [ ] **T0.8 Pre-registration** (`bench/preregistration.md`, `bench/behaviors.yaml`):
  - the 30 behaviors and the 12-behavior core subset;
  - every seeded change with the expected outcome per test and the expected mechanism;
  - metrics and analysis;
  - E1 and E2 kill thresholds.

  Commit it under a signed tag `prereg-v1`; never edit it afterwards (deviations go in `bench/deviations.md`). (FR-B1, FR-B2, FR-B8)
- [ ] **T0.9 Signing key setup** *(can wait until Phase 3)*: create an `ed25519-sk` key on a FIDO2 security key (or a Secure Enclave key with Touch ID), configure git to sign tags with it, and register it in the CI variable `CAIRN_ALLOWED_SIGNERS`. Until then, sign the `prereg-v1` tag with your existing git signing setup.

**Gate G0**: schemas, contracts, decision table, diff fixtures, approval spec, and the pre-registration tag reviewed by you.

## Phase 1: Core with a fake plugin

- [ ] **T1.1 Project skeleton**, config loading, logging, and an import test that keeps HTTP, browser, and model libraries out of the core. (NFR-8)
- [ ] **T1.2 Loaders and validators** for every schema. (FR-C1, FR-C2)
- [ ] **T1.3 Event bus and stores**: JSONL writer, SQLite schema, artifact store; every result records plugin and framework versions. (FR-C7, FR-C8, FR-O6, FR-P4)
- [ ] **T1.4 Plugin registry** and the wrapper that calls plugins and emits events. (FR-P2, FR-P3)
- [ ] **T1.5 Expectation evaluator**: `reads` against the observation diff, `unevaluable`, blocked steps. (FR-C13, FR-C14)
- [ ] **T1.6 Outcome engine** implementing T0.4. (FR-C5, FR-C6)
  Done when: the T0.4 fixture passes completely.
- [ ] **T1.7 Planner**: selection by tag and id, quarantine, reasons. (FR-C3, FR-C11)
- [ ] **T1.8 Scheduler and workers**: isolation, parallelism, `{run.uid}` and `{worker.id}`, serial execution for `hermetic: false`, timeouts. (FR-C4, FR-C18, FR-C12 *(S)*)
- [ ] **T1.9 Fake plugin** that can script every outcome, expectation value, and compound case. (FR-C10)
- [ ] **T1.10 CLI core**: `run` (dev mode) with `--json` output, stable exit codes, and a basic text report. (FR-C9, FR-G1)
- [ ] **T1.11 `explain`** from stored events, basic version. (FR-G2, FR-O7)
- [ ] **T1.12 Core unit tests** using only the fake plugin. (NFR-9, NFR-6)

**Gate G1**: a mixed suite on the fake plugin produces every outcome and compound case with correct explanations, and identical output across 10 runs.

## Phase 2: API plugin

- [ ] **T2.1 OpenAPI ingestion** and normalized operation hashing, including `$ref` resolution. (FR-A1)
- [ ] **T2.2 HTTP step executor**: explicit `op`, templating, binding, JSONPath extraction; JSON bodies and status-only checks for other content types. (FR-A2)
- [ ] **T2.3 Auth helpers.** (FR-A6)
- [ ] **T2.4 Assertion types** with static `reads`: status, header, jsonpath, schema-from-spec, state. (FR-A3)
- [ ] **T2.5 API Observer and response diff**, passing the T0.5 fixtures. (FR-A4, FR-A5, FR-C15)
- [ ] **T2.6 Evidence collector with masking** for secrets and PII, plus a scanning test. (FR-C8, NFR-5)
- [ ] **T2.7 Trace writer (minimal)** so hand-written tests can record observations for E1. Full `record` comes in Phase 3. (FR-R2, partial)
- [ ] **T2.8 Plugin tests** against a local mock server, then the reference API (T6.1).
- [ ] **T2.9 Performance baseline**: measure per-step overhead and planning time; confirm or revise NFR-2 and NFR-3. (NFR-2, NFR-3)
- [ ] **T2.10 E1 run**: the 12-behavior subset against every pre-registered seeded change; record the confusion matrix and apply the E1 kill criteria.

**Gate G2 / Checkpoint E1**: the hand-written explicit-`op` subset against the reference API gives the labeled outcome for every pre-registered seeded change, compound cases included (E1 kill criteria above).

## Phase 3: Record, review, and approval

- [ ] **T3.1 `init --spec`**: project scaffold and spec import. (FR-R1)
- [ ] **T3.2 `record`**: traces written as proposals, with a plain-language rendering of each step. (FR-R2)
- [ ] **T3.3 `review`**: proposals and approved-file diffs with labels. (FR-R3)
- [ ] **T3.4 `approve`**: hash coverage (including project-local plugins), a summary shown before signing, key type recorded, SSH signing per T0.6. (FR-R4, FR-R8, FR-V6)
- [ ] **T3.5 Strict mode and `verify`**: approval verification, trust root from `CAIRN_ALLOWED_SIGNERS` or user config, no bypass, strict guards (missing trace, environment mismatch). (FR-V1, FR-V2, FR-V3, FR-V7, FR-C20, FR-C9)
- [ ] **T3.6 Tamper suite**: every case in FR-V5 as an automated test. Overrun rule: see E2 kill criteria. (FR-V5)
- [ ] **T3.6b Reference CI workflow** *(S)*: pinned engine, trust root from a CI variable, `verify` then `run --strict`, documented repository ruleset and agent token scope. (FR-V8)
- [ ] **T3.7 Quarantine as an approved edit** *(S)*. (FR-C19)

**Gate G3**: starting from a spec, you can go init, write YAML tests, record, review, approve, then strict run, with no test code. Every tamper case is rejected.

## Phase 4: Healing and impact

- [ ] **T4.1 Request-side spec-diff classifier**, passing the T0.5 fixtures. (FR-A7)
- [ ] **T4.2 Impact map**: `impact --spec-diff` and `run --changed`; optional declared `touches` mappings *(C)*. (FR-S1, FR-S2)
- [ ] **T4.3 Healer**: heal proposals for healable fields only, with a dry run showing which expectations still hold. (FR-R5)
- [ ] **T4.4 Value requests and expectation-change requests**, including unambiguous rename and move suggestions (JSONPath-only rewrite) and operationId-rename heals. (FR-R6, FR-R6a, FR-R6b)
- [ ] **T4.5 Heal-limit enforcement test**: an automated test tries to make the healer change an expectation, data value, or arg, or heal a FAIL; the engine refuses each attempt. (FR-R7)
- [ ] **T4.6 `accept-observations`** for additive diffs. (FR-C16)
- [ ] **T4.7 E2 run**: freeze all suites under the signed tag `suites-frozen`, then apply seeded changes by script; measure triage and fix time for cairn-test and Newman; apply the E2 kill criteria. (FR-B9)

**Gate G4 / Checkpoint E2**: for every seeded contract change, `impact` selects exactly the affected tests, and repair produces the pre-registered mechanism (heal, suggestion, value request, request without a suggestion, or none). Zero false heals, zero masking suggestions, and the triage threshold is met.

## Phase 5: Reporting, interface, and polish

- [ ] **T5.1 Run, test, and change views** (HTML + terminal). (FR-O1, FR-O2, FR-O3)
- [ ] **T5.2 JUnit XML export.** (FR-O5)
- [ ] **T5.3 Complete `explain`** for every outcome and reason code. (FR-G2, FR-O7)
- [ ] **T5.4 `migrate`** framework plus a test migration between two dummy schema versions. (FR-M1)
- [ ] **T5.5 Health view** *(S)*. (FR-O4)
- [ ] **T5.6 `doctor`** *(S)*. (FR-V4)
- [ ] **T5.7 MCP server** over the internal API *(S)*. (FR-G3)
- [ ] **T5.8 Deterministic `draft`** *(S)*. (FR-A8)
- [ ] **T5.9 CEL `property` assertion** *(S)*. (FR-A9)
- [ ] **T5.10 Fixtures and parameterized tests** *(S)*. (FR-C17)

**Gate G5**: a fresh checkout with only the stored artifacts can regenerate every report and explanation.

## Phase 6: Benchmark harness

T6.1 and T6.2 (core subset) start in parallel with Phase 1; the rest of the catalog and T6.3 to T6.5 come before E2.

- [ ] **T6.1 Reference target API** (about 12 endpoints, stateful), with a spec. (FR-B1)
- [ ] **T6.2 Seeded changes** as switchable flags, labeled per T0.8. (FR-B1)
- [ ] **T6.3 Time-logging protocol**: how wall-clock time, authored lines, and review time are recorded for every tool and task, with triage and fix logged separately. The same LLM assistant and the same inputs (failing output and spec diff) for all suites. (FR-B3)
- [ ] **T6.4 cairn-test suite** of the 30 behaviors, logged. (FR-B2)
- [ ] **T6.5 Newman suite** of the 30 behaviors, LLM-assisted, logged. (FR-B2, FR-B3)
- [ ] **T6.6 REST Assured suite** *(S)*. (FR-B6)
- [ ] **T6.7 Scoring script**: confusion matrix, triage and fix time with review, false heals, masking suggestions, heal and suggestion acceptance rates, create effort, speed. Results reported against the original and amended pre-registration. (FR-B4, FR-B8)
- [ ] **T6.8 Reproducible run script** writing machine-readable results. (FR-B5)
- [ ] **T6.9 Keploy context run** *(C)*. (FR-B7)

## Phase 7: Evaluation and decision

- [ ] **T7.1 Second plugin proof**: a CLI-command step type using only the contracts, with no core changes. (Acceptance 7)
- [ ] **T7.2 Run the full benchmark** at least 3 times; record variance.
- [ ] **T7.3 Check acceptance criteria 1 to 9** with evidence links.
- [ ] **T7.4 Comparison report**: where cairn-test wins, ties, and loses.
- [ ] **T7.5 Go/no-go decision** on the post-v1 roadmap (UI plugin, model-assisted resolution, skip caching).

**Gate G7 (go/no-go)**
- Go if: classification matches every label, zero false heals, every tamper case rejected, a clear maintenance advantage with review time counted, and the CLI step needed no core changes.
- Revisit the design if: compound cases misclassify for reasons the evaluation rules can't express, or the maintenance advantage disappears once review time is counted.

## Notes for implementation

- Build the decision table (T0.4) and diff fixtures (T0.5) first; they are the test oracles.
- Keep the core free of HTTP, browser, and model libraries (T1.1 import test).
- No inline scripts in test files. Hard cases get a typed step or assertion plugin.
- No model anywhere in v1.
- When a design question comes up mid-build, update `plan.md` first, then the code.