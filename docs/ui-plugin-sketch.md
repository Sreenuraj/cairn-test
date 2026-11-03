# cairn-test UI Plugin Paper Sketch (v1.0)

This document evaluates the applicability of the `cairn-test` core plugin contracts to future UI / Browser testing (e.g. Playwright / Webdriver), identifies domain pressures, and records open questions for the post-v1 roadmap.

---

## 1. Context & Scope

`cairn-test` is designed to be a domain-neutral verification core. While v1 delivers the API plugin, the core contracts (`StepExecutor`, `Observer`, `Fingerprinter`, `AssertionType`, `Healer`, `EvidenceCollector`, `SessionProvider`) were designed to support UI testing without architectural churn.

This sketch stress-tests those contracts against the distinct operational realities of UI automation:
1. Long-lived stateful execution (browser sessions, tabs, cookies).
2. Asynchronous DOM rendering and auto-waits.
3. DOM / client-side nondeterminism.
4. Multimodal observation shapes (accessibility trees, structural DOM, visual screenshots).
5. Visual and trace evidence collection.

---

## 2. Pressures on Core Contracts

### 2.1 `SessionProvider`: Browser & Page Contexts
* **Pressure**: Unlike stateless HTTP calls, browsers have significant initialization overhead (launch, context creation, page navigation) and persistent state (local storage, cookies, active sessions).
* **Contract Evaluation**:
  - `SessionProvider.open(ctx)` initializes the browser instance/context for a worker and attaches it to `ctx.session`.
  - `SessionProvider.close(session)` guarantees graceful teardown and process cleanup.
  - *Contract Verdict*: **Holds.** No contract changes required.

### 2.2 `StepExecutor`: Asynchrony, Selectors & Auto-waits
* **Pressure**: UI steps (`click`, `fill`, `navigate`) require dynamic element resolution, auto-waiting for actionability (visible, enabled, stable), and handling transient overlay states.
* **Contract Evaluation**:
  - `StepExecutor.execute(step, ctx)` wraps action executions within a bounded timeout (`step.timeout_ms`).
  - The step definition specifies target locator strategies (role, text, test-id) in `step.args`.
  - *Contract Verdict*: **Holds.** `StepExecutor` returns a `StepResult` with execution timing, DOM state snapshot, and optional transport/interaction error without needing core modifications.

### 2.3 `Observer`: Observation Shape & Nondeterminism
* **Pressure**: Raw HTML DOM contains dynamic IDs, timestamps, animated CSS classes, and third-party tracker tags that destroy determinism. Conversely, full-page pixel bitmaps suffer from subpixel anti-aliasing jitter.
* **Proposed UI Observation Model**:
  - Primary shape: **Normalized Accessibility (A11y) Tree** (roles, accessible names, states: expanded/checked/disabled).
  - Secondary: Structural bounding box tree of key actionable components.
  - Exclusions: Ephemeral attributes (`class`, transient inline styles, timestamps).
* **Diff Classification**:
  - `additive`: New accessible elements/nodes added to the tree.
  - `identical`: DOM layout shift without role/semantic change, re-ordering of independent sibling nodes.
  - `breaking`: Accessible role removed, label removed, interactive state changed (`disabled` or `hidden`).
* **Contract Verdict**: **Holds.** The core `Observation` schema (`body_shape` as normalized tree) and `ObservationDiff` (`identical`, `additive`, `breaking`) directly model this tree diffing.

### 2.4 `AssertionType`: UI Expectations & `reads`
* **Pressure**: UI assertions check text content, element visibility, URL paths, or visual snapshot comparisons. To calculate `unevaluable`, each assertion must declare what it `reads`.
* **Contract Evaluation**:
  - `reads()` returns accessibility node paths (e.g. `role:button[name="Checkout"]`, `$.url`, `$.title`).
  - If a breaking diff removes or mutates that specific button in the a11y tree, the core outcome engine marks the expectation `unevaluable` (DRIFT), exactly as in the API plugin.
  - *Contract Verdict*: **Holds.**

### 2.5 `EvidenceCollector`: Visual Artifacts & Secret Masking
* **Pressure**: UI debugging requires visual artifacts: full-page screenshots, action video clips, network HAR files, and console logs. Password inputs and masked form fields must never leak into evidence.
* **Contract Evaluation**:
  - `EvidenceCollector.collect(result, ctx)` emits masked artifacts (`image/png`, `application/json`, `text/plain`).
  - Sensitive form fields (`input[type="password"]`, configured CSS selectors) are redacted by the collector before writing to disk.
  - *Contract Verdict*: **Holds.**

---

## 3. Open Questions for Post-v1 UI Implementation

1. **Visual Regression Integration**: Should visual snapshot diffing (pixel thresholding or perceptual hash) live as a separate `AssertionType` (evaluating to true/false) or as part of the `Observer` diff?
   - *Current leaning*: An `AssertionType` (e.g. `visual: { tolerance: 0.02 }`), keeping the `Observer` focused on semantic structural changes (a11y tree).
2. **Selector Self-Healing vs Healer Contract**:
   - When a button ID changes but the role and accessible name remain identical, the `Healer` can propose updating the locator in the trace `resolved` metadata.
3. **Flakiness Quarantine vs Retries**:
   - UI automation often encounters animation race conditions. The core policy rejects blind retries to maintain determinism, but auto-waits inside `StepExecutor` are essential.

---

## 4. Conclusion
The paper sketch confirms that **no changes are needed to the core plugin contracts (`FR-P1`)**. The existing abstractions (`SessionProvider`, `StepExecutor`, `Observer`, `AssertionType`, `EvidenceCollector`) cleanly accommodate browser-driven execution and structural accessibility trees.
