"""
CLI for cairn-test (Phases 1-3: FR-C9, FR-G1, FR-R1..FR-R4, FR-V1..FR-V7).

Commands:
- cairn-test init [--spec ..] [--dir ..]
- cairn-test record [--id ..] [--env ..] [--base-url ..] [--direct]
- cairn-test review [<test_id>] [--json]
- cairn-test approve <test_id> [--key ..] [--identity ..] [--labels ..]
- cairn-test verify [<test_id>] [--env ..] [--json]
- cairn-test run [--strict] [--json] [--tags ..] [--id ..] [--env ..] [--parallelism ..]
- cairn-test explain <run_id> <test_id> [--json]

Exit codes:
0: All passed (or valid)
1: Test failure (FAIL)
2: Test drift (DRIFT)
3: Test error (ERROR) / Verification failure
4: CLI usage or invocation error
"""

from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any
import uuid
import yaml

from cairn_test.config import Config
from cairn_test.core.approval import (
    compute_covers,
    compute_file_sha256,
    resolve_allowed_signers,
    sign_approval,
    verify_approval,
)
from cairn_test.core.events import EventBus, EventStore, FRAMEWORK_VERSION
from cairn_test.core.explain import explain_test
from cairn_test.core.planner import Planner, discover_tests
from cairn_test.core.proposal import (
    compute_review_labels,
    create_trace_proposal,
    render_step_summary,
)
from cairn_test.core.scaffold import init_project
from cairn_test.core.schemas import load_trace, load_yaml, validate_document
from cairn_test.plugins.api.plugin import register_api_plugin
from cairn_test.plugins.api.record import record_test_trace
from cairn_test.plugins.api.spec import OpenAPISpec
from cairn_test.core.plugins import PluginRegistry
from cairn_test.core.scheduler import Scheduler
from cairn_test.plugins.fake import register_fake_plugin

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_DRIFT = 2
EXIT_ERROR = 3
EXIT_CLI_ERROR = 4

def init_command(args: argparse.Namespace) -> int:
    target_dir = Path(args.dir or ".")
    res = init_project(target_dir, spec_path=args.spec)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"Initialized cairn-test project in {res['root']}")
        print(f"Spec: {res['spec']}")
        print("Created directories: " + ", ".join(res["directories"]))
    return EXIT_PASS

def run_command(args: argparse.Namespace) -> int:
    config = Config.load()
    env_profile = args.env or config.default_env
    parallelism = args.parallelism or config.parallelism

    tests_dir = Path(args.tests_dir)
    traces_dir = Path(args.traces_dir)
    store_dir = Path(".cairn-test")

    # Discover tests
    discovered_tests = discover_tests(tests_dir)
    if not discovered_tests:
        if args.json:
            print(json.dumps({"error": f"No test definitions found in {tests_dir}"}))
        else:
            print(f"No test definitions found in {tests_dir}")
        return EXIT_PASS

    # Load recorded traces if traces_dir exists
    traces_map: dict[str, dict[str, Any]] = {}
    if traces_dir.is_dir():
        for p in traces_dir.glob("*.trace.yaml"):
            try:
                tr = load_trace(p)
                traces_map[tr["test"]] = tr
            except Exception:
                pass

    run_id = f"run-{uuid.uuid4().hex[:12]}"
    store = EventStore(base_dir=store_dir)
    bus = EventBus(run_id=run_id, store=store)

    base_url = args.base_url if hasattr(args, "base_url") and args.base_url else config.env_profiles.get(env_profile, {}).get("base_url", "")
    spec = None
    spec_path = args.spec if hasattr(args, "spec") and args.spec else config.spec
    if spec_path and Path(spec_path).is_file():
        spec = OpenAPISpec.load(spec_path)

    registry = PluginRegistry()
    register_fake_plugin(registry)
    register_api_plugin(registry, spec=spec, base_url=base_url)

    tag_filter = [t.strip() for t in args.tags.split(",")] if args.tags else None
    id_filter = [i.strip() for i in args.id.split(",")] if args.id else None

    bus.emit("run.started", {
        "env_profile": env_profile,
        "mode": "strict" if args.strict else "dev",
        "parallelism": parallelism,
        "framework_version": FRAMEWORK_VERSION,
    })

    planner = Planner(
        event_bus=bus,
        tag_filter=tag_filter,
        id_filter=id_filter,
        include_quarantined=args.include_quarantined,
    )
    planned_items = planner.plan_suite(discovered_tests)

    # Verification status
    verification_status: str | dict[str, Any] = "valid"
    if args.strict:
        verification_status = {}
        repo_root = Path(".")
        for item in planned_items:
            is_valid, reason = verify_approval(repo_root, item.test_id, active_env=env_profile)
            if is_valid:
                verification_status[item.test_id] = "valid"
            else:
                verification_status[item.test_id] = (reason or "unapproved", reason or "unapproved")

    scheduler = Scheduler(
        run_id=run_id,
        env_profile=env_profile,
        registry=registry,
        event_bus=bus,
        store=store,
        parallelism=parallelism,
        default_timeout_ms=config.timeout_ms,
    )

    verdicts = scheduler.run_suite(
        planned_items=planned_items,
        traces=traces_map,
        verification_status=verification_status,
    )

    total = len(verdicts)
    passed = sum(1 for v in verdicts if v.outcome == "PASS")
    failed = sum(1 for v in verdicts if v.outcome == "FAIL")
    drifted = sum(1 for v in verdicts if v.outcome == "DRIFT")
    errored = sum(1 for v in verdicts if v.outcome == "ERROR")
    skipped = sum(1 for v in verdicts if v.outcome == "SKIPPED")

    overall_outcome = "PASS"
    exit_code = EXIT_PASS
    if errored > 0:
        overall_outcome = "ERROR"
        exit_code = EXIT_ERROR
    elif failed > 0:
        overall_outcome = "FAIL"
        exit_code = EXIT_FAIL
    elif drifted > 0:
        overall_outcome = "DRIFT"
        exit_code = EXIT_DRIFT

    bus.emit("run.finished", {
        "outcome": overall_outcome,
        "total": total,
        "passed": passed,
        "failed": failed,
        "drifted": drifted,
        "errored": errored,
        "skipped": skipped,
    })

    if args.json:
        report = {
            "run_id": run_id,
            "outcome": overall_outcome,
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "drifted": drifted,
                "errored": errored,
                "skipped": skipped,
            },
            "tests": [
                {
                    "id": item.test_id,
                    "outcome": v.outcome,
                    "reason": v.reason or "",
                    "has_drift_detail": v.has_drift_detail,
                }
                for item, v in zip(planned_items, verdicts)
            ],
        }
        print(json.dumps(report, indent=2))
    else:
        mode_str = "strict" if args.strict else "dev"
        print(f"\ncairn-test run: {run_id} (mode: {mode_str}, env: {env_profile})")
        print("-" * 60)
        for item, v in zip(planned_items, verdicts):
            reason_str = f" - {v.reason}" if v.reason else ""
            print(f"{v.outcome:<7} {item.test_id}{reason_str}")
        print("-" * 60)
        print(
            f"Total: {total} | Passed: {passed} | Failed: {failed} | "
            f"Drifted: {drifted} | Errored: {errored} | Skipped: {skipped}"
        )

    return exit_code

def explain_command(args: argparse.Namespace) -> int:
    store = EventStore(base_dir=".cairn-test")
    info = explain_test(run_id=args.run_id, test_id=args.test_id, store=store)
    if "error" in info:
        if args.json:
            print(json.dumps(info))
        else:
            print(f"Error: {info['error']}")
        return EXIT_CLI_ERROR

    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print(f"\nExplanation for test '{info['test_id']}' in run '{info['run_id']}':")
        print(f"Outcome: {info['outcome']}")
        print(f"Duration: {info['duration_ms']:.2f}ms")
        print(f"Summary: {info['explanation']}")
        if info.get("drift_detail"):
            print(f"Drift Detail: {info['drift_detail']}")
    return EXIT_PASS

def record_command(args: argparse.Namespace) -> int:
    config = Config.load()
    base_url = args.base_url or config.env_profiles.get(config.default_env, {}).get("base_url", "http://localhost:8080")
    tests_dir = Path(args.tests_dir)
    traces_dir = Path(args.traces_dir)
    repo_root = Path(".")

    spec = None
    spec_path = args.spec or config.spec
    if spec_path and Path(spec_path).is_file():
        spec = OpenAPISpec.load(spec_path)

    discovered = discover_tests(tests_dir)
    if args.id:
        target_ids = set(args.id.split(","))
        discovered = [t for t in discovered if t["id"] in target_ids]

    if not discovered:
        print(f"No matching tests found to record in {tests_dir}")
        return EXIT_CLI_ERROR

    recorded_count = 0
    for test_def in discovered:
        test_id = test_def["id"]
        # Record trace
        p = record_test_trace(
            test_def=test_def,
            spec=spec,
            base_url=base_url,
            env_profile=args.env or config.default_env,
            output_dir=traces_dir,
        )
        tr_data = load_trace(p)

        # Compute review labels
        labels = compute_review_labels(repo_root, test_id, current_test_def=test_def, current_trace=tr_data)

        # Write proposal
        prop_path = create_trace_proposal(repo_root, test_id, tr_data, labels=labels)

        # If not direct, keep it in proposals only; if direct was requested, copy to traces/
        if not args.direct:
            p.unlink(missing_ok=True)
            print(f"Recorded proposal for '{test_id}' -> {prop_path} [labels: {', '.join(labels)}]")
        else:
            print(f"Recorded trace for '{test_id}' -> {p} (proposal: {prop_path})")

        recorded_count += 1

    print(f"Successfully recorded {recorded_count} traces/proposals.")
    return EXIT_PASS

def review_command(args: argparse.Namespace) -> int:
    repo_root = Path(".")
    props_dir = repo_root / "proposals"
    tests_dir = Path(args.tests_dir or "tests")

    discovered = discover_tests(tests_dir)
    if args.id:
        target_ids = set(args.id.split(","))
        discovered = [t for t in discovered if t["id"] in target_ids]

    reviews: list[dict[str, Any]] = []

    for test_def in discovered:
        test_id = test_def["id"]
        prop_file = props_dir / f"{test_id}.proposal.yaml"
        prop_trace_file = props_dir / f"{test_id}.trace.yaml"
        current_trace = None
        if prop_trace_file.is_file():
            try:
                current_trace = load_trace(prop_trace_file)
            except Exception:
                pass
        elif (repo_root / "traces" / f"{test_id}.trace.yaml").is_file():
            try:
                current_trace = load_trace(repo_root / "traces" / f"{test_id}.trace.yaml")
            except Exception:
                pass

        labels = compute_review_labels(
            repo_root=repo_root,
            test_id=test_id,
            current_test_def=test_def,
            current_trace=current_trace,
        )

        proposal_info = None
        if prop_file.is_file():
            try:
                proposal_info = load_yaml(prop_file)
            except Exception:
                pass

        reviews.append({
            "test_id": test_id,
            "has_proposal": prop_file.is_file(),
            "labels": labels,
            "summary": proposal_info.get("details", {}).get("summary", proposal_info.get("reason")) if proposal_info else "No pending proposal",
            "steps": proposal_info.get("details", {}).get("steps", []) if proposal_info else [],
        })

    if args.json:
        print(json.dumps(reviews, indent=2))
    else:
        print(f"\ncairn-test review ({len(reviews)} tests evaluated):")
        print("=" * 60)
        for r in reviews:
            prop_flag = "[PROPOSAL PENDING]" if r["has_proposal"] else "[UP TO DATE]"
            print(f"{r['test_id']:<35} {prop_flag:<18} labels: {', '.join(r['labels'])}")
            if r["steps"]:
                for s in r["steps"]:
                    print(f"   -> {s}")
        print("=" * 60)

    return EXIT_PASS

def approve_command(args: argparse.Namespace) -> int:
    repo_root = Path(".")
    test_id = args.id
    test_file = repo_root / "tests" / f"{test_id}.test.yaml"
    if not test_file.is_file():
        print(f"Error: Test definition not found for '{test_id}' at {test_file}")
        return EXIT_CLI_ERROR

    test_def = load_yaml(test_file)

    # Check if a proposal trace exists, promote it to traces/<test_id>.trace.yaml
    prop_trace = repo_root / "proposals" / f"{test_id}.trace.yaml"
    dest_trace = repo_root / "traces" / f"{test_id}.trace.yaml"
    dest_trace.parent.mkdir(parents=True, exist_ok=True)

    if prop_trace.is_file():
        shutil.copy2(prop_trace, dest_trace)

    if not dest_trace.is_file():
        print(f"Error: No trace or proposal trace found for '{test_id}' to approve.")
        return EXIT_CLI_ERROR

    # Compute review labels
    current_trace = load_trace(dest_trace)
    labels = compute_review_labels(repo_root, test_id, current_test_def=test_def, current_trace=current_trace)
    if args.labels:
        extra = [l.strip() for l in args.labels.split(",")]
        labels = sorted(list(set(labels + extra)))

    # Compute coverage SHA-256 for all relevant files
    covers = compute_covers(repo_root, test_id, test_def, trace_path=dest_trace)

    approver_name = args.identity or os.environ.get("USER", "human")
    key_path = args.key or os.environ.get("CAIRN_SIGNING_KEY") or str(Path.home() / ".ssh" / "id_ed25519")

    # Key type
    key_type = "sk-ssh-ed25519@openssh.com" if "sk" in key_path else "ssh-ed25519"

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    appr_doc = {
        "schema": "cairn-test.approval/v1",
        "subject": test_id,
        "covers": covers,
        "approver": {
            "name": approver_name,
            "key": f"key:{approver_name}",
            "key_type": key_type,
        },
        "at": now_iso,
        "labels": labels,
    }

    validate_document(appr_doc, "approval.v1")

    # Display summary before signing
    print(f"\nApproving test '{test_id}':")
    print("-" * 50)
    print(f"Approver: {approver_name} ({key_type})")
    print(f"Labels: {', '.join(labels)}")
    print("Covered files:")
    for fpath, fhash in covers.items():
        print(f"  - {fpath}: {fhash[:16]}...")
    print("-" * 50)

    # Sign with OpenSSH
    try:
        sig_text = sign_approval(appr_doc, key_path=key_path)
    except Exception as exc:
        print(f"Signing failed: {exc}")
        return EXIT_CLI_ERROR

    # Write approval file and signature
    appr_dir = repo_root / "approvals"
    appr_dir.mkdir(parents=True, exist_ok=True)
    appr_file = appr_dir / f"{test_id}.approval.yaml"
    with open(appr_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(appr_doc, f, sort_keys=False)

    sig_file = appr_dir / f"{test_id}.approval.yaml.sig"
    sig_file.write_text(sig_text, encoding="utf-8")

    # Clean up proposal file if it existed
    prop_file = repo_root / "proposals" / f"{test_id}.proposal.yaml"
    prop_file.unlink(missing_ok=True)
    prop_trace.unlink(missing_ok=True)

    print(f"Successfully approved '{test_id}' -> {appr_file}")
    return EXIT_PASS

def verify_command(args: argparse.Namespace) -> int:
    repo_root = Path(".")
    config = Config.load()
    env_profile = args.env or config.default_env
    tests_dir = Path(args.tests_dir or "tests")

    discovered = discover_tests(tests_dir)
    if args.id:
        target_ids = set(args.id.split(","))
        discovered = [t for t in discovered if t["id"] in target_ids]

    results: list[dict[str, Any]] = []
    all_valid = True

    for test_def in discovered:
        test_id = test_def["id"]
        is_valid, reason = verify_approval(repo_root, test_id, active_env=env_profile)
        if not is_valid:
            all_valid = False
        results.append({
            "test_id": test_id,
            "valid": is_valid,
            "reason": reason if not is_valid else None,
        })

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"\ncairn-test verify (env: {env_profile}):")
        print("-" * 50)
        for r in results:
            if r["valid"]:
                print(f"VALID    {r['test_id']}")
            else:
                print(f"INVALID  {r['test_id']} (reason: {r['reason']})")
        print("-" * 50)
        print(f"Total: {len(results)} | Valid: {sum(1 for r in results if r['valid'])} | Invalid: {sum(1 for r in results if not r['valid'])}")

    return EXIT_PASS if all_valid else EXIT_ERROR

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cairn-test",
        description="A trace-based, domain-neutral test framework for the AI era",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize cairn-test project scaffold")
    init_parser.add_argument("--spec", type=str, help="Path or URL to OpenAPI specification")
    init_parser.add_argument("--dir", type=str, default=".", help="Target directory")
    init_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # run command
    run_parser = subparsers.add_parser("run", help="Run test suite")
    run_parser.add_argument("--strict", action="store_true", help="Run in strict mode (verify approvals)")
    run_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    run_parser.add_argument("--tags", type=str, help="Filter tests by tags (comma-separated)")
    run_parser.add_argument("--id", type=str, help="Filter tests by test ID (comma-separated)")
    run_parser.add_argument("--env", type=str, help="Environment profile to target")
    run_parser.add_argument("--base-url", type=str, help="Target API base URL")
    run_parser.add_argument("--spec", type=str, help="OpenAPI spec path")
    run_parser.add_argument("--parallelism", type=int, help="Number of worker threads")
    run_parser.add_argument("--tests-dir", type=str, default="tests", help="Directory containing test files")
    run_parser.add_argument("--traces-dir", type=str, default="traces", help="Directory containing trace files")
    run_parser.add_argument("--include-quarantined", action="store_true", help="Execute quarantined tests")

    # record command
    rec_parser = subparsers.add_parser("record", help="Record traces for tests as inert proposals")
    rec_parser.add_argument("--id", type=str, help="Specific test ID(s) to record (comma-separated)")
    rec_parser.add_argument("--spec", type=str, help="Path to OpenAPI specification")
    rec_parser.add_argument("--base-url", type=str, help="Target API base URL")
    rec_parser.add_argument("--env", type=str, help="Environment profile name")
    rec_parser.add_argument("--direct", action="store_true", help="Write trace directly to traces/ (bypass proposal)")
    rec_parser.add_argument("--tests-dir", type=str, default="tests", help="Directory containing test files")
    rec_parser.add_argument("--traces-dir", type=str, default="traces", help="Directory to write traces")

    # review command
    rev_parser = subparsers.add_parser("review", help="Review proposals and differences with approved files")
    rev_parser.add_argument("id", nargs="?", type=str, help="Optional test ID to review")
    rev_parser.add_argument("--tests-dir", type=str, default="tests", help="Directory containing test files")
    rev_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # approve command
    appr_parser = subparsers.add_parser("approve", help="Sign cryptographic approval for a test")
    appr_parser.add_argument("id", type=str, help="Test ID to approve")
    appr_parser.add_argument("--key", type=str, help="Path to OpenSSH private key")
    appr_parser.add_argument("--identity", type=str, help="Signer identity / name")
    appr_parser.add_argument("--labels", type=str, help="Extra review labels (comma-separated)")

    # verify command
    ver_parser = subparsers.add_parser("verify", help="Verify cryptographic approvals in strict mode")
    ver_parser.add_argument("id", nargs="?", type=str, help="Optional test ID to verify")
    ver_parser.add_argument("--env", type=str, help="Target environment profile")
    ver_parser.add_argument("--tests-dir", type=str, default="tests", help="Directory containing test files")
    ver_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # explain command
    explain_parser = subparsers.add_parser("explain", help="Explain test outcome from stored artifacts")
    explain_parser.add_argument("run_id", type=str, help="Run ID")
    explain_parser.add_argument("test_id", type=str, help="Test ID")
    explain_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    parsed = parser.parse_args()
    if parsed.command == "init":
        code = init_command(parsed)
        sys.exit(code)
    elif parsed.command == "run":
        code = run_command(parsed)
        sys.exit(code)
    elif parsed.command == "record":
        code = record_command(parsed)
        sys.exit(code)
    elif parsed.command == "review":
        code = review_command(parsed)
        sys.exit(code)
    elif parsed.command == "approve":
        code = approve_command(parsed)
        sys.exit(code)
    elif parsed.command == "verify":
        code = verify_command(parsed)
        sys.exit(code)
    elif parsed.command == "explain":
        code = explain_command(parsed)
        sys.exit(code)

if __name__ == "__main__":
    main()
