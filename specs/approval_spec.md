# cairn-test Approval Specification (v1.0)

This document specifies the cryptographic approval mechanism, canonical serialization format, signature namespace, trust-root resolution, and error reason codes for `cairn-test`.

---

## 1. Threat Model & Purpose

Approvals guarantee that **no test definition, recorded trace, data binding, configuration, or local plugin code runs in strict mode without an explicit, verifiable human signature**.

In cairn-test's threat model:
- The coding agent runs as the local OS user and can modify any file in the workspace, including configuration, local engine installs, and git working trees.
- The human signs with a key requiring physical human presence per use (FIDO2 `ed25519-sk` or Secure Enclave Touch ID).
- Enforcement occurs in CI against a pinned engine and a trust root passed via a protected CI variable (`CAIRN_ALLOWED_SIGNERS`).
- Local verification is advisory; CI verification is normative.

---

## 2. Approval Record Structure (`cairn-test.approval/v1`)

An approval is stored at:
`approvals/<id>.approval.yaml`
with its detached SSH signature stored at:
`approvals/<id>.approval.yaml.sig`

### Example
```yaml
schema: cairn-test.approval/v1
subject: create-order
covers:
  tests/create-order.test.yaml: 1d4e68e2...
  traces/create-order.trace.yaml: 88a09bc1...
  data/customers.yaml: 0b7c231a...
  cairn-test.yaml: 5f210d7e...
  plugins/custom_check.py: 9e3a77f0...
approver:
  name: alice
  key: "SHA256:Xk3v8..."
  key_type: sk-ssh-ed25519@openssh.com
at: "2026-11-02T10:05:00Z"
labels:
  - new-test
```

---

## 3. Coverage Requirements (`covers`)

The `covers` mapping binds relative POSIX file paths (relative to repository root) to their hexadecimal lowercase SHA-256 digests.

For a test `<id>`, `covers` **MUST** include:
1. `tests/<id>.test.yaml`: The test definition.
2. `traces/<id>.trace.yaml`: The approved recorded trace.
3. Every file referenced in `data:` (e.g., `data/*.yaml`).
4. Every file referenced in `fixtures:` (setup/teardown steps).
5. `cairn-test.yaml`: The project configuration file.
6. The source of every project-local plugin file in `plugins/` that the test executes or references.

### Hash Computation
To ensure cross-platform reproducibility across operating systems (macOS, Linux, Windows git checkouts):
1. Files are read as bytes.
2. Line endings are normalized to Unix LF (`\n`) before hashing: `content.replace(b"\r\n", b"\n")`.
3. The SHA-256 digest is computed over the normalized bytes and formatted as a 64-character lowercase hex string.

---

## 4. Canonical Serialization for Signing

Detached signatures are created over a canonical serialization of the approval document (excluding the signature itself).

### Canonical Form Rules
1. Format: Canonical JSON (UTF-8 encoded, no Byte Order Mark).
2. Key ordering: Keys at all nesting levels are sorted lexicographically by unicode code point.
3. Whitespace: Compact JSON representation (separators `(",", ":")` without superfluous spaces or indentation).
4. Timestamp format: Normalized ISO 8601 UTC with suffix `Z` (e.g., `2026-11-02T10:05:00Z`).
5. Trailing newline: Exactly one LF (`\n`) byte at the end of the byte sequence.

---

## 5. Signature Creation & Verification

Approvals use standard OpenSSH signatures (`ssh-keygen -Y`).

### 5.1 Namespace
The SSH signature namespace is strictly:
`cairn-test`

### 5.2 Signing Command
```bash
ssh-keygen -Y sign -n cairn-test -f <private_key_path> <canonical_payload_file>
```
The resulting signature is stored in `approvals/<id>.approval.yaml.sig`.

### 5.3 Verification Command
```bash
ssh-keygen -Y verify -n cairn-test -f <allowed_signers_file> -I <signer_identity> -s <sig_file> < <canonical_payload_file>
```

---

## 6. Trust-Root Resolution

The trust root is an OpenSSH `allowed_signers` file format:
```
<identity> namespaces="cairn-test" <key-type> <public-key> [comment]
```

### Lookup Order
1. **CI Environment (Normative)**:
   If environment variable `CAIRN_ALLOWED_SIGNERS` is set:
   - The engine writes the variable content to a secure temporary signers file and evaluates strictly against it.
2. **Local Environment (Advisory)**:
   If `CAIRN_ALLOWED_SIGNERS` is not present:
   - Default user config file: `~/.config/cairn-test/allowed_signers`.
3. **Repository Config Forbidden**:
   - The repository configuration (`cairn-test.yaml` or any workspace file) is **strictly forbidden** from configuring or pointing to the trust root. Any attempt to specify signers within the repository is ignored with an advisory warning.

---

## 7. Strict Mode Reason Codes

When executing in `strict` mode, any failure during approval verification halts execution with outcome `ERROR` and an explicit reason code:

| Reason Code | Condition |
|---|---|
| `unapproved` | No approval file (`approvals/<id>.approval.yaml`) exists for the test. |
| `missing-trace` | No trace file exists for the test definition in strict mode. |
| `tampered` | An approval file exists and its signature is valid, but current content SHA-256 of at least one covered file does not match the hash in `covers`. |
| `bad-signature` | The signature in `.sig` failed OpenSSH cryptographic verification against the canonical payload. |
| `unknown-signer` | The signing key is valid cryptographically but is not present in the resolved `allowed_signers` trust root. |
| `env-mismatch` | The active environment profile does not match the approved environment profile recorded in the trace. |
