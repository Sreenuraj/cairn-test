# cairn-test

A trace-based, domain-neutral test framework for the AI era.

Tests are **data**. How to execute them is a **recorded, reviewed trace**. Replay is deterministic, change (DRIFT) is reported separately from failure (FAIL), and every expectation carries provenance, so coding agents can propose but never weaken or approve what is asserted.

> The verification layer for AI-written software: deterministic, tamper-evident, provenance-tracked.

API testing is the first plugin; UI, mobile, and CLI plugins follow on the same core.

**Status:** design phase (v1 specification). No engine code yet.

## Documents

| Doc | Purpose |
|---|---|
| [docs/core-vision.md](docs/core-vision.md) | Why the core looks like this: AI-era testing landscape and the capabilities a strong core needs. |
| [docs/plan.md](docs/plan.md) | Design: principles, concepts, architecture, plugin contracts, outcomes, schemas, benchmark. Source of truth. |
| [docs/requirements.md](docs/requirements.md) | Functional and non-functional requirements with stable IDs, plus v1 acceptance criteria. |
| [docs/tasks.md](docs/tasks.md) | Phased task list with gates, mapped to requirement IDs. |