"""
Security and configuration diagnostic tool (T5.6, FR-V4).

Reports checkable security assumptions:
1. Signing key type (warns unless security-key or Secure Enclave).
2. Trust-root source (warns when local rather than environment/CI).
3. Engine pinning in CI workflow (warns if unpinned).
"""

from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any
import yaml

@dataclass
class DiagnosticCheck:
    id: str
    name: str
    status: str  # "OK" | "WARN" | "FAIL"
    message: str
    remediation: str | None = None

class Doctor:
    """Runs security and environment diagnostic checks."""

    def __init__(self, repo_root: Path | None = None):
        self.repo_root = repo_root or Path(".")

    def check_signing_key(self, key_path: Path | None = None) -> DiagnosticCheck:
        target_key = key_path or Path(os.environ.get("CAIRN_SIGNING_KEY", Path.home() / ".ssh" / "id_ed25519_sk"))
        if not target_key.is_file():
            # Fallback to standard key
            target_key = Path.home() / ".ssh" / "id_ed25519"

        if not target_key.is_file():
            return DiagnosticCheck(
                id="signing_key",
                name="OpenSSH Signing Key",
                status="WARN",
                message="No default OpenSSH private key found at ~/.ssh/id_ed25519_sk or ~/.ssh/id_ed25519",
                remediation="Generate an ed25519-sk key with: ssh-keygen -t ed25519-sk",
            )

        key_name = target_key.name.lower()
        if "sk" in key_name:
            return DiagnosticCheck(
                id="signing_key",
                name="OpenSSH Signing Key",
                status="OK",
                message=f"Hardware security key / Secure Enclave key detected ({target_key.name})",
            )
        else:
            return DiagnosticCheck(
                id="signing_key",
                name="OpenSSH Signing Key",
                status="WARN",
                message=f"Standard software key detected ({target_key.name}). Security model assumes keys that require physical presence.",
                remediation="Upgrade to a FIDO2 security key or Secure Enclave key (ssh-keygen -t ed25519-sk)",
            )

    def check_trust_root(self) -> DiagnosticCheck:
        if os.environ.get("CAIRN_ALLOWED_SIGNERS"):
            return DiagnosticCheck(
                id="trust_root",
                name="Trust Root Source",
                status="OK",
                message="Trust root configured via CAIRN_ALLOWED_SIGNERS environment variable (protected CI / host source)",
            )

        local_signers = Path.home() / ".config" / "cairn-test" / "allowed_signers"
        if local_signers.is_file():
            return DiagnosticCheck(
                id="trust_root",
                name="Trust Root Source",
                status="WARN",
                message=f"Trust root loaded from local user config ({local_signers}). For CI environments, use CAIRN_ALLOWED_SIGNERS.",
                remediation="In CI pipelines, store allowed signers in protected secret CAIRN_ALLOWED_SIGNERS",
            )

        return DiagnosticCheck(
            id="trust_root",
            name="Trust Root Source",
            status="FAIL",
            message="No trust root found in CAIRN_ALLOWED_SIGNERS or ~/.config/cairn-test/allowed_signers",
            remediation="Add trusted public keys to CAIRN_ALLOWED_SIGNERS or ~/.config/cairn-test/allowed_signers",
        )

    def check_ci_pinning(self) -> DiagnosticCheck:
        wf_dir = self.repo_root / ".github" / "workflows"
        if not wf_dir.is_dir():
            return DiagnosticCheck(
                id="ci_pinning",
                name="CI Engine Pinning",
                status="WARN",
                message="No GitHub Actions workflow directory found (.github/workflows/)",
                remediation="Add reference CI workflow in .github/workflows/cairn-test.yml with pinned engine",
            )

        found_pinned = False
        workflow_files = list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))
        for wf_path in workflow_files:
            text = wf_path.read_text(encoding="utf-8")
            if "cairn-test" in text:
                # Check for pinned commit or tag or hash
                if "@" in text or "sha256" in text or "==" in text:
                    found_pinned = True
                    break

        if found_pinned:
            return DiagnosticCheck(
                id="ci_pinning",
                name="CI Engine Pinning",
                status="OK",
                message="CI workflow pins cairn-test engine specification",
            )
        else:
            return DiagnosticCheck(
                id="ci_pinning",
                name="CI Engine Pinning",
                status="WARN",
                message="CI workflow runs cairn-test without explicit version/digest pinning",
                remediation="Pin engine version or commit SHA in CI workflow to prevent engine tampering",
            )

    def run_all(self, key_path: Path | None = None) -> list[DiagnosticCheck]:
        return [
            self.check_signing_key(key_path),
            self.check_trust_root(),
            self.check_ci_pinning(),
        ]
