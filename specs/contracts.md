# cairn-test Plugin Contracts Specification (v1.0)

This document specifies the language-neutral plugin contracts for `cairn-test`.

## 1. Architectural Rules and Invariants

The core enforces strict boundaries between plugins and the engine:

1. **Plugins return data only, never outcomes.**
   - Plugins never assign `PASS`, `FAIL`, `DRIFT`, `ERROR`, or `SKIPPED`.
   - The outcome engine in core is the sole authority assigning outcomes and expectation evaluations (`true`, `false`, `unevaluable`).
2. **Plugins never emit events or write to the event bus.**
   - The core wraps all plugin invocations, captures timings/context, and emits standard lifecycle events (`step.executed`, `observation.diffed`, `expectation.evaluated`, etc.).
3. **Plugins never read, verify, or sign approvals.**
   - Approvals, cryptographic signatures, and trust-root verifications belong entirely to the core verification engine.
4. **Plugins never mutate test definitions or approved traces.**
   - Repairs are returned as inert `Proposal` objects to be approved by a human signature.
5. **Plugins must be deterministic and side-effect isolated.**
   - Given the same `ResolvedStep` and `RunContext`, plugins must produce deterministic results.
   - Resource cleanup must be guaranteed via `SessionProvider.close()`.

---

## 2. Core Data Models

### 2.1 `RunContext`
Execution context passed to plugins:
- `run_id`: `str` — Unique identifier for the test run.
- `worker_id`: `str` — Identifier for the executing worker.
- `env_profile`: `str` — Active environment profile (e.g., `staging`, `local`).
- `variables`: `dict[str, Any]` — Current resolved test variables (including `{run.uid}`, `{worker.id}`).
- `session`: `Any | None` — Active session object if provided by a `SessionProvider`.

### 2.2 `ResolvedStep`
Fully resolved step ready for execution:
- `id`: `str` — Step identifier.
- `kind`: `str` — Step type (e.g., `"http"`, `"fake"`).
- `operation`: `str` — Operation identifier (e.g., OpenAPI operationId).
- `method`: `str` — HTTP method or action verb.
- `path`: `str` — Target endpoint path (templated variables resolved).
- `params`: `dict[str, Any]` — Arg locations (query, path, header, body).
- `headers`: `dict[str, str]` — Resolved request headers.
- `body`: `Any | None` — Serialized request body.
- `auth`: `str | None` — Resolved auth token or credential.
- `timeout_ms`: `int` — Step timeout in milliseconds.

### 2.3 `StepResult`
Raw execution result returned by a `StepExecutor`:
- `step_id`: `str` — Identifier of the executed step.
- `status_code`: `int | None` — Transport or protocol status code (e.g., HTTP status).
- `headers`: `dict[str, str]` — Response headers.
- `data`: `Any | None` — Parsed response body or raw return data.
- `duration_ms`: `float` — Execution duration.
- `transport_error`: `str | None` — Network/transport error description if execution failed prior to a valid response.

### 2.4 `Observation`
Comparable structural shape produced by an `Observer`:
- `status`: `int` — Observed status code.
- `headers`: `list[str]` — Normalized list of present header names.
- `body_shape`: `Any` — Structural representation of the body (keys and data types, ignoring literals and array lengths).

### 2.5 `ObservationDiff`
Difference between recorded and observed observations:
- `changes`: `list[DiffChange]` where each `DiffChange` has:
  - `path`: `str` — Dot/JSONPath path of the changed element (e.g., `$.status`, `headers.content-type`, `$.items.total`).
  - `kind`: `str` — Enum: `"identical"`, `"additive"`, `"breaking"`.
  - `recorded`: `Any` — Recorded value/type.
  - `observed`: `Any` — Observed value/type.
  - `detail`: `str` — Human-readable reason.

### 2.6 `Fingerprint`
Pre-execution input hash:
- `data`: `dict[str, str]` — Map of component hashes (e.g., `{"op_hash": "c40e..."}`).

---

## 3. Plugin Interfaces

### 3.1 `StepExecutor`
Executes an explicit step against the system under test.
```python
class StepExecutor(Protocol):
    kind: str  # e.g., "http", "fake", "cli"

    def execute(self, step: ResolvedStep, ctx: RunContext) -> StepResult:
        """
        Executes a resolved step.
        MUST NOT raise exceptions for normal non-2xx responses (e.g., 404, 500 are valid StepResults).
        MUST populate transport_error for connection refused, timeout, or DNS resolution failure.
        """
        ...
```

### 3.2 `Observer`
Extracts normalized structural observations and computes deterministic diffs.
```python
class Observer(Protocol):
    def observe(self, result: StepResult) -> Observation:
        """
        Extracts status, headers, and normalized body shape from a StepResult.
        Ignores array lengths and key ordering.
        """
        ...

    def compare(self, recorded: Observation, observed: Observation) -> ObservationDiff:
        """
        Compares recorded and observed observations.
        Classifies every change as identical, additive, or breaking.
        """
        ...
```

### 3.3 `Fingerprinter`
Computes pre-run fingerprints and reports touched operations for impact analysis.
```python
class Fingerprinter(Protocol):
    def pre(self, step: ResolvedStep, ctx: RunContext) -> Fingerprint:
        """
        Computes input hash for the operation before step execution.
        """
        ...

    def touches(self, test: dict, trace: dict | None) -> list[str]:
        """
        Returns list of operation identifiers touched by the test/trace.
        """
        ...
```

### 3.4 `AssertionType`
Evaluates a typed expectation and statically declares which observation paths it depends on.
```python
class AssertionType(Protocol):
    name: str  # e.g., "status", "header", "jsonpath", "schema", "property", "state"

    def reads(self, spec: dict) -> list[str]:
        """
        Returns the observation paths this assertion reads.
        Used by the core to decide if a breaking diff makes the assertion 'unevaluable'.
        Example: {"jsonpath": "$.user.email"} -> ["$.user.email"]
                 {"status": 200} -> ["$.status"]
        """
        ...

    def evaluate(self, spec: dict, result: StepResult, ctx: RunContext) -> bool | str:
        """
        Evaluates the assertion against the result.
        Returns True if satisfied, False if violated, or 'missing' if an asserted path does not exist.
        MUST NOT decide outcome (the core handles true/false/unevaluable precedence).
        """
        ...
```

### 3.5 `Healer`
Proposes deterministic repairs for healable trace fields based on spec diffs.
```python
class Healer(Protocol):
    def propose(self, step: ResolvedStep, diff: dict, ctx: RunContext) -> dict | None:
        """
        Inspects spec diff and proposes modifications to healable fields:
        (operation mapping, method, path, parameter placement, headers).
        MUST NEVER propose modifications to expectations, data values, or test files.
        """
        ...
```

### 3.6 `EvidenceCollector`
Collects and masks execution artifacts for persistent storage.
```python
class EvidenceCollector(Protocol):
    def collect(self, result: StepResult, ctx: RunContext) -> list[dict]:
        """
        Returns masked execution evidence (raw requests, responses, timings).
        Configured secrets and PII MUST be masked before return.
        """
        ...
```

### 3.7 `SessionProvider` (Optional)
Manages shared state or connection sessions.
```python
class SessionProvider(Protocol):
    def open(self, ctx: RunContext) -> Any:
        """Initializes a new session."""
        ...

    def close(self, session: Any) -> None:
        """Closes and cleans up session resources."""
        ...
```

---

## 4. What a Plugin Must NEVER Do
1. **NEVER compute or return a verdict**: No `PASS`, `FAIL`, `DRIFT`, `ERROR`.
2. **NEVER call the event bus directly**: Core handles event logging.
3. **NEVER modify or sign approvals**: Core verifies SHA-256 hashes against trusted signers.
4. **NEVER auto-apply proposals**: All proposals require human review and approval.
5. **NEVER invent synthetic data values**: New required fields trigger `value-request`.
