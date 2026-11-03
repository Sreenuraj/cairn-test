"""
Scanning test for secret and PII masking (T2.6, FR-C8, NFR-5).
"""

from cairn_test.contracts import RunContext, StepResult
from cairn_test.plugins.api.evidence import ApiEvidenceCollector, EvidenceMasker

SENSITIVE_LEAKS = [
    "super-secret-password-xyz123",
    "jwt.secret.token.here",
    "123-45-6789",  # SSN
    "my_api_key_value_999",
]

def test_evidence_masking_scan():
    collector = ApiEvidenceCollector()
    ctx = RunContext(run_id="run-leak-scan", worker_id="w-0", env_profile="test")

    # StepResult containing raw credentials and sensitive PII
    result = StepResult(
        step_id="login_step",
        status_code=200,
        headers={
            "authorization": "Bearer jwt.secret.token.here",
            "x-api-key": "my_api_key_value_999",
            "content-type": "application/json",
        },
        data={
            "user": "alice",
            "password": "super-secret-password-xyz123",
            "customer": {
                "ssn": "123-45-6789",
                "notes": "Customer SSN is 123-45-6789 and auth is Bearer jwt.secret.token.here",
            },
            "token": "jwt.secret.token.here",
        },
        duration_ms=45.0,
    )

    artifacts = collector.collect(result, ctx)
    assert len(artifacts) == 2

    # Scanning test: Verify NONE of the sensitive leaks appear anywhere in serialized artifacts
    all_content = " ".join(
        str(a.content) if isinstance(a.content, str) else a.content.decode("utf-8")
        for a in artifacts
    )

    for leak in SENSITIVE_LEAKS:
        assert leak not in all_content, f"NFR-5 VIOLATION: Sensitive leak '{leak}' was found in evidence!"

    # Verify redaction markers present
    assert "[REDACTED]" in all_content
    print("NFR-5 Scanning test PASSED: All secrets and PII redacted from evidence!")

if __name__ == "__main__":
    test_evidence_masking_scan()
