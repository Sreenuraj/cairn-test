# cairn-test Core Vision: Testing in the AI Era

Companion to `plan.md`, `requirements.md`, and `tasks.md`. This document explains *why* the core is shaped the way it is and records the v1.1 scope decisions. `plan.md` is the source of truth for *what* is built.

## 1. What changed

Research into the 2025–2026 testing landscape (sources in section 7) shows three shifts.

1. **The test suite is becoming the main oversight mechanism.** Coding agents produce more code than people can review, so oversight collapses onto the automated suite. A green run now carries more weight and deserves less trust.
2. **Agents game the suites that judge them.** SpecBench measured a consistent gap between visible tests (which every frontier agent passes) and held-out tests, growing with task size, with failures that include deliberate exploits such as memorizing test inputs. Practitioner reports describe loosened assertions, skipped tests, special-cased inputs, and edited fixtures or CI config.
3. **AI testing tools have split into three execution models.**
   - **Scripts plus AI**: a model writes and repairs conventional test code (Playwright Test Agents: planner, generator, healer; Mabl, Testim). Deterministic, but healing can change what is asserted.
   - **Runtime agents**: an agent decides at run time what to do and check (QA.tech, BrowserUse). Broad coverage, hard to reproduce or verify, with recurring token cost.
   - **Resolve once, replay**: a model resolves an action once and later runs replay a cache (Stagehand). Cheap, but the cache is not a reviewable contract and has no notion of an outcome.

Credible vendors agree on one point: **verdicts must be deterministic**.

## 2. Where cairn-test fits

cairn-test is "record once, replay" with governance on top: tests are data, execution is a recorded and approved trace, change (DRIFT) is separate from failure (FAIL), and repairs are proposals that can change *how* a step runs, never *what* is asserted. Approvals are signed by a human key, so in strict mode an agent cannot quietly change what counts as passing.

Long-term positioning: **a domain-neutral verification layer for AI-written software**. v1 is deliberately narrower (section 5).

## 3. What a strong core needs (long-term)

| # | Capability | v1 status |
|---|---|---|
| 1 | Tamper-evident expectations: signed approvals, strict verification, review labels | **In v1** (signature-based) |
| 2 | Suite-strength measurement (seeded faults, mutation-style) | Benchmark seeded changes only; general fault seeding post-v1 |
| 3 | Richer checks: property, metamorphic, differential, statistical | CEL `property` is a should; the rest post-v1 |
| 4 | Two loops: an exploration agent proposes, deterministic tests verify | Post-v1 |
| 5 | Agents as first-class users | `--json` everywhere and `explain` in v1; MCP is a should |
| 6 | Change-based selection | Spec-diff in v1; code-diff post-v1 |
| 7 | A general Observation model with identical / additive / breaking diffs | **In v1** (API); UI paper sketch |
| 8 | Framework fundamentals as data: fixtures, parameterization, sessions, isolation, quarantine | Isolation in v1 (M); fixtures, parameterization, quarantine are should |

## 4. Design decisions that make the core sound

1. **`unevaluable` is decided by the core**, from the paths an assertion reads and the observation diff. It is not a plugin opinion. A missing value with no diff entry to explain it is `false`.
2. **Compound cases are normative.** A contract change plus a false expectation is FAIL with drift detail; the full table is in `plan.md` 6.3 and is a test fixture.
3. **Blocked steps** (a missing extracted variable) are `unevaluable (blocked)`; the test outcome follows the cause of the blocking step.
4. **Additive diffs never silently update traces**; updates are batched proposals that need approval.
5. **Healing is deterministic and spec-diff based.** Healable fields: operation mapping, method, path, parameter placement, header mapping. New required parameters produce a value request, never an invented value.
6. **Identity comes from signatures made with a key that needs a touch per use; enforcement happens in CI.** The threat model is explicit, and tamper-evidence is claimed only within it.
7. **Rename and move suggestions are precision-first.** A suggestion appears only for an unambiguous same-type candidate, rewrites only the JSONPath, and needs a signature. A suggestion that would mask a bug counts as a failure.

## 5. Scope decisions (answers to the design reviews, v1.1 and v1.2)

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | Skip caching in v1? | **Deferred.** Design kept in `plan.md` appendix A. | In CI nearly every run follows a deploy, which changes the service version, so cache hits would be rare; meanwhile it carries the highest correctness risk and cost. |
| 2 | Which thesis must v1 prove? | **"Change is not failure"**: correct DRIFT/FAIL/PASS classification including compound cases, plus lower maintenance with review time counted. The maintenance advantage is expected mainly from **triage** (structured DRIFT reports), then impact selection, then deterministic repair; triage and fix time are measured separately. Integrity ships as a tested mechanism, not a benchmark claim. | This is the novel, falsifiable part. With no model, deterministic repair alone is unlikely to beat an LLM-assisted competitor on fix time, so the claim must rest on triage. If triage shows no advantage, the thesis fails. |
| 3 | Threat model | The agent runs as the same OS user. It can run any shell command and edit anything local: the repo, `~/.config`, even the installed engine. It cannot sign with the human's key, edit CI workflows or variables, or push to `main`. Local verification is advisory; **the guarantee comes from CI** with a pinned engine and the trust root in a CI variable. | "Outside the repo" protects nothing if the agent's user can write there. The only places the agent can't reach are a hardware key and CI settings. |
| 4 | Where the signing key lives | A **FIDO2 security key (`ed25519-sk`, touch per signature)** is recommended. A Secure Enclave key with Touch ID per use is supported. A passphrase-protected file never loaded into an ssh-agent is tolerated with a warning. Agent-loaded or unencrypted keys are unsupported. `approve` shows what will be signed before the touch. | A key in a running ssh-agent, or an unencrypted file, can be used by anything running as the user. Only a physical action per signature backs the claim. |
| 5 | Do expectations declare what they depend on? | Built-in assertions work out their `reads` from their own definition; custom assertion types must declare them. No new field in test files. | Keeps tests simple and makes `unevaluable` decidable. |
| 6 | Healable trace fields | Operation mapping, method, path, parameter placement, header mapping. Never expectations, data values, args, or observations. | Separates "how" from "what" precisely enough to test. |
| 7 | Selection | Spec-diff only, plus optional declared mappings. | Black-box API testing has no code-to-operation map; competitors can match spec-diff selection, so it is not claimed as a differentiator. |
| 8 | Competitor suites, N, trusted | All suites LLM-assisted with the same assistant; N = 30 fixed behaviors; "trusted" means every expectation reviewed by a human; review time is logged for every tool. | The realistic 2026 baseline, and it makes the comparison fair. |
| 9 | pytest/Playwright adapter | **Rejected for v1.** | Conflicts with "no test code"; approvals cannot inspect assertions written inside code. |
| 10 | Time budget and continue criteria | E1, classification: 4 weeks, hard stop at 6, on a 12-behavior subset in dev mode. Signing and the tamper suite are moved out of E1. If it slips: cut scope to 6 behaviors with every compound case kept, then decide at week 6. Kill: any compound misclassification whose fix needs a special case or a rule outside `plan.md` 6.2–6.3. E2, maintenance: 5 weeks (hard stop 7). Kill if triage is not at least 30% faster than Newman. | Tests the riskiest assumption first and cheaply, and moves the likeliest overrun (the tamper suite) off the critical path. |
| 11 | Benchmark honesty | **Pre-registration**: behaviors, seeded changes, expected labels and mechanisms, metrics, and kill thresholds are committed under a signed tag before any suite is written. Suites are frozen under a signed tag before seeded changes are enabled. Deviations are logged, and results are reported against the original and amended versions. | Tuning cases after seeing results is the easiest way to fool yourself, even with the same assistant for every suite. |

Also decided: no model anywhere in v1 (intent steps and model-assisted drafting are post-v1; drafting is deterministic and optional); JSON bodies only; PII masking added to NFR-5; `migrate` is a must; NFR-2 and NFR-3 are provisional until measured (T2.9); the implementation language is decided first (T0.1, default Python).

## 6. What cairn-test deliberately does not do

- Let a model decide PASS or FAIL.
- Let any automated actor change, weaken, or delete an expectation without a fresh human signature.
- Claim protection beyond its stated threat model.
- Hide evidence: every outcome and selection decision is explainable from stored artifacts.

## 7. Sources

Verified (page opened):
- SpecBench: Measuring Reward Hacking in Long-Horizon Coding Agents, arXiv:2605.21384 (v2, Sep 2026): https://arxiv.org/abs/2605.21384
- QA Wolf, "AI Testing Tools 2026: 12 Compared by How They Really Work" (Feb 2026): https://www.qawolf.com/blog/the-12-best-ai-testing-tools-in-2026
- QA.tech, "The 12 Best Agentic QA Tools in 2026" (Sep 2026): https://qa.tech/blog/best-agentic-qa-tools-in-2026
- Playwright Test Agents (planner, generator, healer): https://playwright.dev/docs/test-agents
- Stagehand action caching overview (Dec 2025): https://stevengonsalvez.com/tools-tips/stagehand
- StepTo, "Coding Agents Reward Hacking: Why Green Tests Lie" (Oct 2026): https://stepto.net/blog/coding-agents-reward-hacking-test-tampering-mutation-testing-2026

Cited from search results only (page not opened):
- "Test Oracle Automation in the Era of LLMs", ACM TOSEM: https://dl.acm.org/doi/abs/10.1145/3715107 (access returned HTTP 403)
- Stagehand caching documentation: https://docs.stagehand.dev