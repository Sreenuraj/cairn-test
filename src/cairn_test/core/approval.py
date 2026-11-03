"""
Cryptographic approval and strict-mode verification engine (T3.4, T3.5, FR-R4, FR-R8, FR-V1..FR-V7).

Implements specs/approval_spec.md:
- SHA-256 with Unix LF normalization for covered files.
- Canonical JSON serialization for signing.
- OpenSSH detached signatures via `ssh-keygen -Y sign` and `ssh-keygen -Y verify`.
- Trust root resolution: CAIRN_ALLOWED_SIGNERS (CI) -> ~/.config/cairn-test/allowed_signers (local).
- Repository config is strictly forbidden from setting the trust root.
- Strict-mode reason codes: unapproved, missing-trace, tampered, bad-signature, unknown-signer, env-mismatch.
"""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any
import yaml

from cairn_test.core.schemas import load_yaml, validate_document

SIGNATURE_NAMESPACE = "cairn-test"

def normalize_bytes(data: bytes) -> bytes:
    """Normalize line endings to Unix LF (\n)."""
    return data.replace(b"\r\n", b"\n")

def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of a file with normalized LF line endings."""
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    raw = path.read_bytes()
    norm = normalize_bytes(raw)
    return hashlib.sha256(norm).hexdigest()

def canonicalize_approval_payload(data: dict[str, Any]) -> bytes:
    """
    Canonical JSON serialization per specs/approval_spec.md:
    - Keys sorted lexicographically at all nesting levels.
    - Compact separators (",", ":").
    - UTF-8 encoded with exactly one trailing newline.
    """
    compact_str = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return compact_str.encode("utf-8") + b"\n"

def compute_covers(
    repo_root: Path,
    test_id: str,
    test_def: dict[str, Any],
    trace_path: Path | None = None,
) -> dict[str, str]:
    """
    Computes SHA-256 digests for all files covered by an approval:
    1. tests/<test_id>.test.yaml
    2. traces/<test_id>.trace.yaml (or custom trace path)
    3. cairn-test.yaml (if present)
    4. Referenced data files in data:
    5. Project-local plugins in plugins/
    """
    covers: dict[str, str] = {}

    # 1. Test definition
    test_file = repo_root / "tests" / f"{test_id}.test.yaml"
    if test_file.is_file():
        rel = str(test_file.relative_to(repo_root))
        covers[rel] = compute_file_sha256(test_file)

    # 2. Trace file
    tr_file = trace_path or (repo_root / "traces" / f"{test_id}.trace.yaml")
    if tr_file.is_file():
        rel = str(tr_file.relative_to(repo_root))
        covers[rel] = compute_file_sha256(tr_file)

    # 3. cairn-test.yaml
    cfg_file = repo_root / "cairn-test.yaml"
    if cfg_file.is_file():
        covers["cairn-test.yaml"] = compute_file_sha256(cfg_file)

    # 4. Data bindings
    data_bindings = test_def.get("data", {})
    if isinstance(data_bindings, dict):
        for val in data_bindings.values():
            if isinstance(val, dict) and "from" in val:
                from_ref = str(val["from"]).split("#")[0]
                df = repo_root / from_ref
                if df.is_file():
                    covers[from_ref] = compute_file_sha256(df)

    # 5. Project-local plugin files
    plugins_dir = repo_root / "plugins"
    if plugins_dir.is_dir():
        for pf in sorted(plugins_dir.glob("**/*.py")):
            if pf.is_file():
                rel = str(pf.relative_to(repo_root))
                covers[rel] = compute_file_sha256(pf)

    return covers

def sign_approval(
    approval_data: dict[str, Any],
    key_path: Path | str,
    namespace: str = SIGNATURE_NAMESPACE,
) -> str:
    """
    Sign canonical approval payload using OpenSSH ssh-keygen -Y sign.
    Returns the detached signature text (ASCII armored).
    """
    canonical_payload = canonicalize_approval_payload(approval_data)
    key_path_obj = Path(key_path).expanduser().resolve()
    if not key_path_obj.is_file():
        raise FileNotFoundError(f"Signing private key not found at {key_path_obj}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        payload_file = Path(tmp_dir) / "approval.payload"
        payload_file.write_bytes(canonical_payload)

        sig_file = Path(tmp_dir) / "approval.payload.sig"
        sig_file.unlink(missing_ok=True)

        cmd = [
            "ssh-keygen",
            "-Y", "sign",
            "-n", namespace,
            "-f", str(key_path_obj),
            str(payload_file),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"OpenSSH signing failed: {res.stderr.strip()}")

        if not sig_file.is_file():
            raise RuntimeError("OpenSSH signing did not generate signature file")

        return sig_file.read_text(encoding="utf-8")

def resolve_allowed_signers(repo_root: Path) -> tuple[Path | None, bool]:
    """
    Resolve OpenSSH allowed_signers trust root per specs/approval_spec.md:
    1. Environment variable CAIRN_ALLOWED_SIGNERS (CI normative).
    2. ~/.config/cairn-test/allowed_signers (local user config advisory).
    Repository config files are strictly forbidden from specifying signers.
    Returns (path_to_signers_file, is_ci).
    """
    # 1. CI variable
    ci_signers = os.environ.get("CAIRN_ALLOWED_SIGNERS")
    if ci_signers and ci_signers.strip():
        # Write to temporary file for ssh-keygen -Y verify
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix="_allowed_signers", delete=False)
        tmp.write(ci_signers.strip() + "\n")
        tmp.flush()
        tmp.close()
        return Path(tmp.name), True

    # 2. Local user config
    local_signers = Path.home() / ".config" / "cairn-test" / "allowed_signers"
    if local_signers.is_file():
        return local_signers, False

    return None, False

def verify_approval(
    repo_root: Path,
    test_id: str,
    active_env: str = "local",
    strict_trace_check: bool = True,
) -> tuple[bool, str | None]:
    """
    Strict-mode verification for test_id per specs/approval_spec.md:
    Checks in sequence:
    1. Approval file exists -> 'unapproved'
    2. Trace file exists -> 'missing-trace'
    3. Active env profile matches trace env_profile -> 'env-mismatch'
    4. Hashes of covered files match current files -> 'tampered'
    5. Signature file exists -> 'bad-signature'
    6. Cryptographic signature check -> 'bad-signature'
    7. Signer identity & key in allowed_signers -> 'unknown-signer'
    Returns (True, None) on success, or (False, reason_code).
    """
    appr_file = repo_root / "approvals" / f"{test_id}.approval.yaml"
    if not appr_file.is_file():
        return False, "unapproved"

    trace_file = repo_root / "traces" / f"{test_id}.trace.yaml"
    if strict_trace_check and not trace_file.is_file():
        return False, "missing-trace"

    # Load trace and check environment
    if trace_file.is_file():
        try:
            trace_data = load_yaml(trace_file)
            trace_env = trace_data.get("env_profile", "local")
            if trace_env != active_env:
                return False, "env-mismatch"
        except Exception:
            return False, "missing-trace"

    # Load approval file
    try:
        appr_data = load_yaml(appr_file)
        validate_document(appr_data, "approval.v1")
    except Exception:
        return False, "tampered"

    covers = appr_data.get("covers", {})
    if not covers:
        return False, "tampered"

    # Verify each covered file hash against current workspace
    for rel_path, expected_hash in covers.items():
        covered_file = repo_root / rel_path
        if not covered_file.is_file():
            return False, "tampered"
        current_hash = compute_file_sha256(covered_file)
        if current_hash.lower() != expected_hash.lower():
            return False, "tampered"

    # Check signature file
    sig_file = repo_root / "approvals" / f"{test_id}.approval.yaml.sig"
    if not sig_file.is_file():
        return False, "bad-signature"

    canonical_payload = canonicalize_approval_payload(appr_data)

    # 1. First verify cryptographic integrity (check-novalidate)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_sig = Path(tmp_dir) / "sig.txt"
        tmp_sig.write_text(sig_file.read_text(encoding="utf-8"))

        check_cmd = [
            "ssh-keygen",
            "-Y", "check-novalidate",
            "-n", SIGNATURE_NAMESPACE,
            "-s", str(tmp_sig),
        ]
        res_chk = subprocess.run(check_cmd, input=canonical_payload, capture_output=True)
        if res_chk.returncode != 0:
            return False, "bad-signature"

        # 2. Next verify against allowed_signers trust root
        signers_path, is_ci = resolve_allowed_signers(repo_root)
        if not signers_path or not signers_path.is_file():
            return False, "unknown-signer"

        approver = appr_data.get("approver", {})
        signer_id = approver.get("name") or approver.get("key") or test_id

        verify_cmd = [
            "ssh-keygen",
            "-Y", "verify",
            "-n", SIGNATURE_NAMESPACE,
            "-f", str(signers_path),
            "-I", str(signer_id),
            "-s", str(tmp_sig),
        ]
        res_v = subprocess.run(verify_cmd, input=canonical_payload, capture_output=True)
        if res_v.returncode != 0:
            # Also try without matching -I (in case identity in allowed_signers is different or key-only)
            # Match identity from principal
            return False, "unknown-signer"

    return True, None

