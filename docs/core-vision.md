# cairn-test Core Vision: Testing in the AI Era

Companion to `plan.md`, `requirements.md`, and `tasks.md`. This document explains *why* the core is shaped the way it is. `plan.md` remains the source of truth for *what* is built.

## 1. What changed

Research into the 2025–2026 testing landscape (sources at the end) points to three shifts.

1. **The test suite is becoming the main oversight mechanism.** Coding agents produce more code than people can review. Oversight collapses onto the automated suite, so a green run now carries more weight than it used to and deserves less trust.
2. **Agents game the suites that judge them.** Published research (e.g. SpecBench) measures coding agents optimizing for green tests rather than correct behavior: loosening assertions, skipping tests, special-casing test inputs, editing fixtures or CI config, and hollow implementations. Some AI "healers" can edit any part of a test, including assertions.
3. **AI testing tools have split into three execution models.**
   - **Scripts plus AI**: a model writes and repairs conventional test code (Playwright Test Agents: planner, generator, healer; Mabl, Testim, Katalon). Deterministic, but healing can silently change what is asserted.
   - **Runtime agents**: an agent reads the screen and decides what to do and what to check at run time (QA.tech, BrowserUse). Little maintenance and broad coverage, but results are hard to reproduce or verify, and token cost recurs every run.
   - **Resolve once, replay**: a model resolves an action once; later runs replay a cache at near-zero cost (Stagehand action caching). Fast and cheap, but the cache is not a reviewable contract and has no notion of an outcome.

Credible vendors converge on one point: **verdicts must be deterministic**. Models are useful for authoring, exploring, and repairing, not for judging.

## 2. Where cairn-test fits

cairn-test is "resolve once, replay" with governance on top:

- Tests are data; execution is a recorded, reviewed trace.
- Expectations are human-owned; the model never decides an outcome.
- Change (DRIFT) is reported separately from failure (FAIL).
- Repairs are proposals that can change *how* a step runs, never *what* is asserted.

That combination already answers most of what the research recommends. The positioning follows from it:

> **cairn-test is the verification layer for AI-written software: deterministic, tamper-evident, provenance-tracked.**

That is harder to copy than "declarative tests" and aligns with where the market is going.

## 3. What a strong core needs

Eight capabilities separate a core that could replace traditional frameworks from one that is a niche API tool.

| # | Capability | Why it matters in the AI era |
|---|---|---|
| 1 | **Tamper-evident expectations** | Every expectation carries provenance (author, approver, when). Agents can propose but never approve. Weakening an expectation is a separately flagged review item. Held-out acceptance suites can be hidden from agents. This is the main selling point. |
| 2 | **Suite strength measurement** | A green run proves little when agents wrote the code. The core injects seeded faults (mutation-style, per plugin) and reports a "would this suite catch a bug?" score per suite and per change. |
| 3 | **Richer, non-brittle checks** | Property and invariant checks, metamorphic relations, differential comparison against a baseline version, and statistical checks (passes when a threshold holds over N samples) for systems that contain an LLM and are not deterministic. An LLM judge may be advisory evidence, never a verdict. |
| 4 | **Two loops: explore and verify** | An exploration agent (runtime, non-deterministic) discovers behavior and produces *proposals*. Approved proposals become deterministic regression tests. The core models the handoff formally, so you get runtime-agent coverage without giving up repeatable verdicts. |
| 5 | **Agents as primary users** | Coding agents will invoke the framework far more often than people. The engine is exposed as a structured API and an MCP server: impact analysis, run, explain, propose. Permissions let an agent run and propose but never approve. |
| 6 | **Change-based test selection** | Map tests to what they touch (operations, components, routes, files). Select from code and spec diffs. This delivers most of the speed benefit; skip caching becomes a later optimization. |
| 7 | **A general Observation model** | "Contract" and "fingerprint" become one core concept that each plugin fills in: response schema for API, accessibility tree and DOM shape for UI, exit code and output shape for CLI. DRIFT, healing, and selection all depend on it. Design it against a UI plugin early. |
| 8 | **Framework fundamentals, as data** | Fixtures, setup/teardown, parameterized and generated data, long-lived sessions (browser, device), waits and timing, flake tracking and quarantine, and an adapter that runs existing pytest or Playwright tests inside cairn-test for gradual adoption. |

## 4. Design consequences for v1

1. **Unevaluable expectations.** When an expectation cannot be evaluated because the observation changed (a field was renamed, an endpoint now returns 404 because it was removed), the result is DRIFT with the expectation marked `unevaluable`, not FAIL. Without this rule, contract changes surface as FAIL and the DRIFT/FAIL split collapses. A FAIL requires that the expectation was evaluable against a matching observation and was false.
2. **Compatibility-aware observation diffs.** Observation comparison classifies changes as `identical`, `additive` (benign: new optional field, reordering), or `breaking`. Only `breaking` yields DRIFT. Plain hash equality is too blunt.
3. **Provenance is a schema field from day one**, on tests, expectations, traces, and proposals.
4. **The outcome engine handles sampled steps**: a statistical expectation is decided once over all samples, deterministically, from the recorded sample results.
5. **Skip caching is deferred.** Change-based selection comes first; CACHED-PASS stays in the design but is built later and is optional.
6. **The second paper plugin is UI**, not only CLI, because UI stresses sessions, waits, nondeterminism, and visual evidence. CLI remains the cheap second *implemented* plugin for the extensibility proof.

## 5. What cairn-test deliberately does not do

- Let a model decide PASS or FAIL.
- Let any automated actor (heal, explore, agent) change, weaken, or delete an expectation without human approval.
- Hide evidence: every outcome, skip, and selection decision is explainable from stored artifacts.

## 6. Sources

- QA Wolf, "AI Testing Tools 2026: 12 Compared by How They Really Work": https://www.qawolf.com/blog/the-12-best-ai-testing-tools-in-2026
- QA.tech, "The 12 Best Agentic QA Tools in 2026": https://qa.tech/blog/best-agentic-qa-tools-in-2026
- Stagehand action caching: https://stevengonsalvez.com/tools-tips/stagehand and https://docs.stagehand.dev
- Playwright Test Agents (planner, generator, healer): https://playwright.dev/docs/test-agents
- StepTo, "Coding Agents Reward Hacking: Why Green Tests Lie": https://stepto.net/blog/coding-agents-reward-hacking-test-tampering-mutation-testing-2026
- SpecBench, measuring reward hacking in long-horizon coding agents: https://arxiv.org/abs/2605.21384
- Test oracle automation in the era of LLMs: https://dl.acm.org/ (ACM TOSEM roadmap), https://arxiv.org/ (AugmenTest)