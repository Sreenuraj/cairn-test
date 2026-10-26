# cairn-test

A trace-based, domain-neutral test framework for the AI era.

Tests are **data**. How to execute them is a **recorded, approved trace**. Replay is deterministic, and **change (DRIFT) is reported separately from failure (FAIL)**. Approvals are signed with a human key, so in strict mode a coding agent cannot quietly change what counts as passing.

API testing is the first plugin; UI, mobile, and CLI plugins follow on the same core.

**Status:** design v1.2 (specification). No engine code yet.

**What v1 must prove:** correct DRIFT/FAIL/PASS classification across seeded contract changes, bugs, benign changes, and combinations of them, plus lower maintenance effort (review time included) than an LLM-assisted Newman suite.

## Documents

| Doc | Purpose |
|---|---|
| [docs/core-vision.md](docs/core-vision.md) | Why: the AI-era testing landscape, long-term capabilities, and the v1.1 scope decisions. |
| [docs/plan.md](docs/plan.md) | Design (source of truth): principles, contracts, outcome rules, schemas, approvals and threat model, healing, benchmark. |
| [docs/requirements.md](docs/requirements.md) | Requirements with stable IDs and v1 acceptance criteria. |
| [docs/tasks.md](docs/tasks.md) | Phased tasks, gates, and timeboxed checkpoints. |