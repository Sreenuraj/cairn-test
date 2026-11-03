# cairn-test Benchmark Pre-Registration (v1.0)

This document is the normative benchmark pre-registration for `cairn-test`. Per [`requirements.md` FR-B8](file:///Users/sreenuraj/cairn-test/docs/requirements.md) and [`plan.md` §15](file:///Users/sreenuraj/cairn-test/docs/plan.md), this document is frozen and committed under tag `prereg-v1` before benchmark suites or seeded changes are evaluated. Any modifications after tag creation are recorded exclusively in [`bench/deviations.md`](file:///Users/sreenuraj/cairn-test/bench/deviations.md).

---

## 1. Benchmark Scope & Catalog

The benchmark tests a reference stateful store API (~12 endpoints: auth, products, orders, refunds) across **N = 30** behaviors defined in [`bench/behaviors.yaml`](file:///Users/sreenuraj/cairn-test/bench/behaviors.yaml).

### 1.1 Checkpoint Subsets
- **E1 Checkpoint (Classification)**: The 12-behavior core subset (`B01` through `B12`). Tests are hand-written declarative YAML run in `dev` mode.
- **E2 Checkpoint (Maintenance)**: All 30 behaviors (`B01` through `B30`), comparing `cairn-test` against an LLM-assisted Newman test suite.

---

## 2. Seeded Changes & Expected Oracles

Each seeded change is switchable via configuration in the reference target service.

### 2.1 Contract Changes (Request Side)
| ID | Description | Affected Endpoints | Expected Outcome | Expected Repair Mechanism |
|---|---|---|---|---|
| `C-REQ-1` | Move parameter `status` from query parameter to request body | `POST /orders/search` | **DRIFT** | Heal proposal (parameter placement) |
| `C-REQ-2` | Endpoint path changed from `/orders` to `/v2/orders` (same operationId) | `POST /orders` | **DRIFT** | Heal proposal (path rewrite) |
| `C-REQ-3` | Rename operationId `createOrder` to `placeOrder` (method, path, schemas unchanged) | `POST /orders` | **DRIFT** | Heal proposal (operation mapping) |
| `C-REQ-4` | Add a new required parameter `delivery_type` to order request body | `POST /orders` | **DRIFT** | Value request (human input required; never synthetic) |

### 2.2 Contract Changes (Response Side)
| ID | Description | Affected Endpoints | Expected Outcome | Expected Repair Mechanism |
|---|---|---|---|---|
| `C-RES-1` | Rename field `total` to `grand_total` in order response | `POST /orders`, `GET /orders/{id}` | **DRIFT** | Expectation-change suggestion (JSONPath rewrite `$.total` -> `$.grand_total`) |
| `C-RES-2` | Move field `customer_id` into nested object `customer.id` | `GET /orders/{id}` | **DRIFT** | Expectation-change suggestion (JSONPath rewrite `$.customer_id` -> `$.customer.id`) |
| `C-RES-3` | Change field `total` data type from number to string (`"49.98"`) | `POST /orders` | **DRIFT** | Expectation-change request without suggestion |
| `C-RES-4` | Remove endpoint `GET /products/{id}/inventory` (returns 404) | `GET /products/{id}/inventory` | **DRIFT** | None (breaking status; operation missing) |

### 2.3 Behavioral Bugs
| ID | Description | Affected Endpoints | Expected Outcome | Expected Repair Mechanism |
|---|---|---|---|---|
| `BUG-1` | Line total calculation error (off-by-10% tax calculation) | `POST /orders` | **FAIL** | None (candidate defect) |
| `BUG-2` | Validation regression: accepts negative item quantity | `POST /orders` | **FAIL** | None (candidate defect) |
| `BUG-3` | Authorization bypass: returns order belonging to different user | `GET /orders/{id}` | **FAIL** | None (candidate defect) |
| `BUG-4` | Pagination off-by-one: skips first item on offset > 0 | `GET /products` | **FAIL** | None (candidate defect) |
| `BUG-5` | Refund limit logic broken: permits refunding more than order total | `POST /refunds` | **FAIL** | None (candidate defect) |

### 2.4 Benign Changes
| ID | Description | Affected Endpoints | Expected Outcome | Expected Repair Mechanism |
|---|---|---|---|---|
| `BEN-1` | New optional field `tracking_hint` added to order response | `POST /orders` | **PASS** (with additive note) | None (batch proposal via `accept-observations`) |
| `BEN-2` | Key order in JSON response scrambled | All endpoints | **PASS** | None |
| `BEN-3` | Millisecond precision added to timestamp strings | All endpoints | **PASS** | None |

### 2.5 Compound Changes (Normative)
| ID | Description | Expected Outcome | Precedence Rule |
|---|---|---|---|
| `CMP-1` | Contract change (`C-RES-1`: `total` renamed) + Behavioral bug (`BUG-1`: wrong item status) | **FAIL** | FAIL > DRIFT (drift attached as detail) |
| `CMP-2` | Field rename (`total` -> `grand_total`) + bug in calculation of that field | **FAIL** | FAIL > DRIFT |
| `CMP-3` | Benign additive field (`BEN-1`) + Behavioral bug (`BUG-2`) | **FAIL** | FAIL > PASS |
| `CMP-4` | Drift in step 1 (`C-REQ-2`: endpoint moved) blocks step 2 token extraction | **DRIFT** | DRIFT (step 2 unevaluable `blocked-by:step1`) |

---

## 3. Metrics & Statistical Protocol

Runs will be executed at least 3 times; medians and variance will be reported.

1. **Classification Accuracy (Confusion Matrix)**:
   - Evaluated across all seeded runs:
     - Contract-only -> must be 100% DRIFT.
     - Bug-only -> must be 100% FAIL.
     - Benign -> must be 100% PASS.
     - Compound -> must follow normative precedence table (FAIL with drift detail, or blocked DRIFT).
2. **Maintenance Effort**:
   - **Triage Time**: Elapsed wall-clock time from test run completion to verified identification of affected tests and root-cause classification (contract change vs bug), including human review time.
   - **Fix Time**: Elapsed wall-clock time from triage completion to green run, including human review and approval time.
3. **Repair Quality**:
   - **False Heals**: Must be **0**. A proposal that changes an expectation, data value, or converts a defect into PASS is a benchmark failure.
   - **Masking Suggestions**: Must be **0**. An expectation suggestion that conceals a defect is a benchmark failure.
   - **Proposal Acceptance Rate**: Percentage of generated proposals accepted without manual modification.
4. **Authoring Effort & Execution Speed**:
   - Authored lines of YAML vs Newman test script lines (reported for transparency, not claimed as primary win).
   - Replay duration per test.

---

## 4. Kill Criteria & Thresholds

### 4.1 E1 Kill Criteria (Classification)
1. **Continue** if all 12 core behaviors match their labeled outcomes across contract-only, bug-only, benign, and compound cases.
2. **Stop and rethink the core outcome model** if *any* compound case misclassifies and fixing it requires:
   - A per-test or per-assertion special case;
   - A rule outside `plan.md` §6.2 and §6.3;
   - Semantic knowledge an observation cannot carry.
3. **Stop** if a benign change produces DRIFT that additive observation diff rules cannot express.
4. **Hard Stop**: 6 weeks maximum timebox.

### 4.2 E2 Kill Criteria (Maintenance)
1. **Stop** if median *triage time* (human review included) for `cairn-test` is not lower than the LLM-assisted Newman suite by at least **30%**.
2. **Stop** if any false heal or masking suggestion occurs.
