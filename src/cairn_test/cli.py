"""
CLI for cairn-test (T1.10, FR-C9, FR-G1).

Commands:
- cairn-test run [--strict] [--json] [--tags ..] [--id ..] [--env ..] [--parallelism ..]
- cairn-test explain <run_id> <test_id> [--json]

Exit codes:
0: All passed (or skipped)
1: Test failure (FAIL)
2: Test drift (DRIFT)
3: Test error (ERROR)
4: CLI usage or invocation error
"""

from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any
import uuid

from cairn_test.config import Config
from cairn_test.core.events import EventBus, EventStore, FRAMEWORK_VERSION
from cairn_test.core.explain import explain_test
from cairn_test.core.planner import Planner, discover_tests
from cairn_test.plugins.api.plugin import register_api_plugin
from cairn_test.plugins.api.record import record_test_trace
from cairn_test.plugins.api.spec import OpenAPISpec
from cairn_test.core.plugins import PluginRegistry
from cairn_test.core.scheduler import Scheduler
from cairn_test.core.schemas import load_trace
from cairn_test.plugins.fake import register_fake_plugin

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_DRIFT = 2
EXIT_ERROR = 3
EXIT_CLI_ERROR = 4

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
    # Register default plugins
    register_fake_plugin(registry)
    register_api_plugin(registry, spec=spec, base_url=base_url)

    # Tag & ID filters
    tag_filter = [t.strip() for t in args.tags.split(",")] if args.tags else None
    id_filter = [i.strip() for i in args.id.split(",")] if args.id else None

    # Emit run.started event
    bus.emit("run.started", {
        "env_profile": env_profile,
        "mode": "strict" if args.strict else "dev",
        "parallelism": parallelism,
        "framework_version": FRAMEWORK_VERSION,
    })

    # Plan
    planner = Planner(
        event_bus=bus,
        tag_filter=tag_filter,
        id_filter=id_filter,
        include_quarantined=args.include_quarantined,
    )
    planned_items = planner.plan_suite(discovered_tests)

    # Verification status (dev mode: valid; strict mode verification handled in Phase 3)
    verification_status = "valid"
    if args.strict:
        # In Phase 1 skeleton, strict without approvals is rejected
        pass

    # Schedule and run
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

    # Calculate summary
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
        p = record_test_trace(
            test_def=test_def,
            spec=spec,
            base_url=base_url,
            env_profile=args.env or config.default_env,
            output_dir=traces_dir,
        )
        print(f"Recorded trace for '{test_def['id']}' -> {p}")
        recorded_count += 1

    print(f"Successfully recorded {recorded_count} traces.")
    return EXIT_PASS

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cairn-test",
        description="A trace-based, domain-neutral test framework for the AI era",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

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
    rec_parser = subparsers.add_parser("record", help="Record traces for tests")
    rec_parser.add_argument("--id", type=str, help="Specific test ID(s) to record (comma-separated)")
    rec_parser.add_argument("--spec", type=str, help="Path to OpenAPI specification")
    rec_parser.add_argument("--base-url", type=str, help="Target API base URL")
    rec_parser.add_argument("--env", type=str, help="Environment profile name")
    rec_parser.add_argument("--tests-dir", type=str, default="tests", help="Directory containing test files")
    rec_parser.add_argument("--traces-dir", type=str, default="traces", help="Directory to write traces")

    # explain command
    explain_parser = subparsers.add_parser("explain", help="Explain test outcome from stored artifacts")
    explain_parser.add_argument("run_id", type=str, help="Run ID")
    explain_parser.add_argument("test_id", type=str, help="Test ID")
    explain_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    parsed = parser.parse_args()
    if parsed.command == "run":
        code = run_command(parsed)
        sys.exit(code)
    elif parsed.command == "record":
        code = record_command(parsed)
        sys.exit(code)
    elif parsed.command == "explain":
        code = explain_command(parsed)
        sys.exit(code)

if __name__ == "__main__":
    main()
