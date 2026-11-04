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

def fetch_remote_spec(url: str, dest_dir: Path) -> Path:
    import urllib.parse
    import urllib.request
    parsed = urllib.parse.urlparse(url)
    raw_name = Path(parsed.path).name
    if not raw_name or not (raw_name.endswith(".yaml") or raw_name.endswith(".yml") or raw_name.endswith(".json")):
        raw_name = "openapi.yaml"
    dest_path = dest_dir / raw_name
    print(f"Downloading remote specification from {url}...")
    req = urllib.request.Request(url, headers={"User-Agent": "cairn-test/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        content = resp.read()
    dest_path.write_bytes(content)
    print(f"Saved remote specification to {dest_path}")
    return dest_path

def init_command(args: argparse.Namespace) -> int:
    target_dir = Path(args.dir or ".").resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    spec_arg = args.spec
    orig_spec_url = None
    if spec_arg and (spec_arg.startswith("http://") or spec_arg.startswith("https://")):
        orig_spec_url = spec_arg
        try:
            local_spec_path = fetch_remote_spec(spec_arg, target_dir)
            spec_arg = str(local_spec_path)
        except Exception as e:
            print(f"Error downloading remote specification from {spec_arg}: {e}", file=sys.stderr)
            return EXIT_CLI_ERROR

    res = init_project(target_dir, spec_path=spec_arg, spec_url=orig_spec_url)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"Initialized cairn-test project in {res['root']}")
        print(f"Spec: {res['spec']}")
        if "local_url" in res:
            print(f"Target Environment (local): {res['local_url']}")
        if "staging_url" in res:
            print(f"Target Environment (staging): {res['staging_url']}")
        print("Created directories: " + ", ".join(res["directories"]))
        print(f"Scaffolded practitioner & AI agent guide in README.md")
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
            props_dir = Path("proposals")
            if props_dir.is_dir() and any(props_dir.glob("*.proposal.yaml")):
                print("Tip: Found pending draft proposals. Run 'cairn-test draft --promote' to activate them into tests/.")
        return EXIT_PASS

    if getattr(args, "changed", False):
        old_spec_arg = None
        new_spec_arg = None
        if getattr(args, "spec_diff", None):
            old_spec_arg = args.spec_diff[0]
            new_spec_arg = args.spec_diff[1]
        else:
            old_spec_arg = args.old_spec or config.spec
            new_spec_arg = args.new_spec
        if not old_spec_arg or not new_spec_arg or not Path(old_spec_arg).is_file() or not Path(new_spec_arg).is_file():
            print("Error: --changed requires --spec-diff OLD NEW or --old-spec and --new-spec")
            return EXIT_CLI_ERROR

        with open(old_spec_arg, "r", encoding="utf-8") as f:
            old_spec = yaml.safe_load(f) or {}
        with open(new_spec_arg, "r", encoding="utf-8") as f:
            new_spec = yaml.safe_load(f) or {}

        from cairn_test.core.healing import ImpactAnalyzer
        from cairn_test.plugins.api.spec_diff import SpecDiffClassifier
        analyzer = ImpactAnalyzer(SpecDiffClassifier())
        affected = analyzer.find_affected_tests(discovered_tests, old_spec, new_spec)
        affected_ids = {a["test_id"] for a in affected}
        discovered_tests = [t for t in discovered_tests if t["id"] in affected_ids]
        if not discovered_tests:
            if args.json:
                print(json.dumps({"run_id": "none", "outcome": "PASS", "summary": {"total": 0, "passed": 0, "failed": 0, "drifted": 0, "errored": 0, "skipped": 0}, "tests": []}))
            else:
                print("No tests affected by spec diff.")
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

    # Optional report exports
    if getattr(args, "junit", None) or getattr(args, "html", None):
        test_verdicts_data = [
            {
                "test_id": item.test_id,
                "outcome": v.outcome,
                "reason": v.reason or "",
                "duration_ms": getattr(v, "duration_ms", 0.0),
            }
            for item, v in zip(planned_items, verdicts)
        ]
        if getattr(args, "junit", None):
            from cairn_test.core.reporting import generate_junit_xml
            xml_str = generate_junit_xml(run_id, test_verdicts_data)
            p = Path(args.junit)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(xml_str, encoding="utf-8")
        if getattr(args, "html", None):
            from cairn_test.core.reporting import generate_html_report
            html_str = generate_html_report(
                run_id=run_id,
                run_summary={
                    "total": total,
                    "passed": passed,
                    "failed": failed,
                    "drifted": drifted,
                    "errored": errored,
                    "skipped": skipped,
                    "outcome": overall_outcome,
                },
                test_verdicts=test_verdicts_data,
                metadata={"env_profile": env_profile, "mode": "strict" if args.strict else "dev"},
            )
            p = Path(args.html)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(html_str, encoding="utf-8")

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

    discovered = []
    target = getattr(args, "target", None)

    # 1. Target provided as positional argument
    if target:
        target_path = Path(target)
        if target_path.is_file():
            # Direct test file path
            try:
                td = load_yaml(target_path)
                if isinstance(td, dict) and "id" in td:
                    discovered = [td]
            except Exception as e:
                print(f"Error loading test file {target_path}: {e}", file=sys.stderr)
                return EXIT_CLI_ERROR
        elif Path(f"{target}.example").is_file():
            # If target has .example counterpart (e.g. sample.test.yaml.example), copy and load
            ex_path = Path(f"{target}.example")
            shutil.copy2(ex_path, target_path)
            td = load_yaml(target_path)
            discovered = [td]
        else:
            # 1. Look in tests_dir for matching test ID or filename
            disc_all = discover_tests(tests_dir)
            discovered = [t for t in disc_all if t.get("id") == target or t.get("id") == target.replace(".test.yaml", "")]

            # 2. If not found in tests_dir, check if target is a draft proposal in proposals/ to auto-promote
            if not discovered:
                prop_file = repo_root / "proposals" / f"{target}.proposal.yaml"
                if prop_file.is_file():
                    from cairn_test.core.draft import promote_drafts
                    promoted = promote_drafts(repo_root, target_ids=[target])
                    if promoted:
                        discovered = [load_yaml(promoted[0])]

    elif args.id:
        target_ids = set(args.id.split(","))
        disc_all = discover_tests(tests_dir)
        discovered = [t for t in disc_all if t["id"] in target_ids]
        if not discovered:
            from cairn_test.core.draft import promote_drafts
            promoted = promote_drafts(repo_root, target_ids=list(target_ids))
            if promoted:
                disc_all = discover_tests(tests_dir)
                discovered = [t for t in disc_all if t["id"] in target_ids]
    else:
        discovered = discover_tests(tests_dir)
        if not discovered:
            from cairn_test.core.draft import promote_drafts
            promoted = promote_drafts(repo_root)
            if promoted:
                print(f"Auto-promoted {len(promoted)} draft proposal(s) into {tests_dir}/")
                discovered = discover_tests(tests_dir)

    if not discovered:
        print(f"No matching tests found to record in {tests_dir}")
        print("Tip: If you ran 'cairn-test draft', run 'cairn-test draft --promote' to promote drafts to tests/.")
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
    discovered_ids = {t["id"] for t in discovered}

    target_id_filter = getattr(args, "id_flag", None) or getattr(args, "id", None)
    target_ids = set(target_id_filter.split(",")) if target_id_filter else set()
    if target_id_filter:
        discovered = [t for t in discovered if t["id"] in target_ids]

    reviews: list[dict[str, Any]] = []

    # 1. Process discovered tests in tests/
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
            "kind": proposal_info.get("kind", "test") if proposal_info else "test",
            "labels": labels,
            "summary": proposal_info.get("details", {}).get("summary", proposal_info.get("reason")) if proposal_info else "No pending proposal",
            "steps": proposal_info.get("details", {}).get("steps", []) if proposal_info else [],
        })

    # 2. Process pending proposals in proposals/ that are not yet in tests/ (e.g. draft proposals)
    if props_dir.is_dir():
        for pfile in sorted(props_dir.glob("*.proposal.yaml")):
            try:
                pdata = load_yaml(pfile)
            except Exception:
                continue
            if not isinstance(pdata, dict):
                continue
            test_id = pdata.get("test") or pfile.name.replace(".proposal.yaml", "")
            if test_id in discovered_ids:
                continue
            if target_id_filter and test_id not in target_ids:
                continue

            kind = pdata.get("kind", "proposal")
            labels = [kind, "pending-promotion"]
            step_names = []
            if kind == "draft":
                draft_test = pdata.get("details", {}).get("draft_test", {})
                step_names = [s.get("op") or s.get("id") for s in draft_test.get("steps", [])]

            reviews.append({
                "test_id": test_id,
                "proposal_id": pdata.get("id"),
                "has_proposal": True,
                "kind": kind,
                "labels": labels,
                "summary": pdata.get("reason", f"Pending {kind} proposal"),
                "steps": step_names,
            })

    if args.json:
        print(json.dumps(reviews, indent=2))
    else:
        print(f"\ncairn-test review ({len(reviews)} items evaluated):")
        print("=" * 60)
        for r in reviews:
            prop_flag = "[PROPOSAL PENDING]" if r["has_proposal"] else "[UP TO DATE]"
            print(f"{r['test_id']:<35} {prop_flag:<18} labels: {', '.join(r['labels'])}")
            if r.get("summary"):
                print(f"   Summary: {r['summary']}")
            if r["steps"]:
                for s in r["steps"]:
                    print(f"   -> {s}")
        print("=" * 60)
        draft_count = sum(1 for r in reviews if r.get("kind") == "draft" and "pending-promotion" in r.get("labels", []))
        if draft_count > 0:
            print(f"\nFound {draft_count} draft test proposals. To promote them to runnable tests in tests/, run:")
            print("  cairn-test draft --promote")

    return EXIT_PASS

def approve_command(args: argparse.Namespace) -> int:
    repo_root = Path(".")
    raw_target = getattr(args, "id_flag", None) or args.id
    test_id = raw_target
    test_file = repo_root / "tests" / f"{test_id}.test.yaml"

    if not test_file.is_file():
        # 1. Check if raw_target is a direct file path (e.g. tests/sample.test.yaml)
        target_path = Path(raw_target)
        if target_path.is_file():
            try:
                td = load_yaml(target_path)
                if isinstance(td, dict) and "id" in td:
                    test_file = target_path
                    test_id = td["id"]
            except Exception:
                pass
        else:
            # 2. Check all test files in tests/ to find matching test ID
            for tf in sorted((repo_root / "tests").glob("*.test.yaml")):
                try:
                    td = load_yaml(tf)
                    if isinstance(td, dict) and td.get("id") == test_id:
                        test_file = tf
                        break
                except Exception:
                    pass

    if not test_file.is_file():
        # 3. Check if test_id matches a draft proposal in proposals/
        prop_file = repo_root / "proposals" / f"{test_id}.proposal.yaml"
        if prop_file.is_file():
            from cairn_test.core.draft import promote_drafts
            promoted = promote_drafts(repo_root, target_ids=[test_id])
            if promoted:
                test_file = promoted[0]
        if not test_file.is_file():
            print(f"Error: Test definition not found for '{test_id}' at {test_file}")
            return EXIT_CLI_ERROR

    test_def = load_yaml(test_file)
    if not test_id and isinstance(test_def, dict):
        test_id = test_def.get("id", raw_target)

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
    covers = compute_covers(repo_root, test_id, test_def, test_path=test_file, trace_path=dest_trace)

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

    # Clean up proposal files if they existed
    for prop_f in (repo_root / "proposals").glob(f"{test_id}.*"):
        prop_f.unlink(missing_ok=True)

    print(f"Successfully approved '{test_id}' -> {appr_file}")
    return EXIT_PASS

def verify_command(args: argparse.Namespace) -> int:
    repo_root = Path(".")
    config = Config.load()
    env_profile = args.env or config.default_env
    tests_dir = Path(args.tests_dir or "tests")

    discovered = discover_tests(tests_dir)
    target_id_filter = getattr(args, "id_flag", None) or getattr(args, "id", None)
    if target_id_filter:
        target_ids = set(target_id_filter.split(","))
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

def _load_spec_pair(args: argparse.Namespace, repo_root: Path, config: Config) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """Helper to resolve old and new specs from args (--spec-diff [1 or 2 files] or --old-spec/--new-spec)."""
    if getattr(args, "spec_diff", None):
        diff_args = args.spec_diff
        if len(diff_args) >= 2:
            old_p, new_p = Path(diff_args[0]), Path(diff_args[1])
            if not old_p.is_file():
                return None, None, f"Old spec not found at {old_p}"
            if not new_p.is_file():
                return None, None, f"New spec not found at {new_p}"
            old_spec = yaml.safe_load(old_p.read_text(encoding="utf-8")) or {}
            new_spec = yaml.safe_load(new_p.read_text(encoding="utf-8")) or {}
            return old_spec, new_spec, None
        elif len(diff_args) == 1:
            new_p = Path(diff_args[0])
            if not new_p.is_file():
                return None, None, f"Spec file not found at {new_p}"
            new_spec = yaml.safe_load(new_p.read_text(encoding="utf-8")) or {}
            # Attempt to retrieve base spec from git show HEAD:<rel_path>
            try:
                rel = new_p.resolve().relative_to(repo_root.resolve())
                res = subprocess.run(["git", "show", f"HEAD:{rel}"], capture_output=True, text=True, cwd=str(repo_root))
                if res.returncode == 0 and res.stdout.strip():
                    old_spec = yaml.safe_load(res.stdout) or {}
                    return old_spec, new_spec, None
            except Exception:
                pass
            return None, None, f"Could not retrieve base spec from git HEAD for '{new_p}'. Please specify both: --spec-diff <old_spec> <new_spec>"
    else:
        old_spec_path = Path(args.old_spec or config.spec or "openapi.yaml")
        new_spec_path = Path(args.new_spec) if args.new_spec else Path("")
        if not old_spec_path.is_file():
            return None, None, f"Old spec not found at {old_spec_path}"
        if not new_spec_path.is_file():
            return None, None, f"New spec not found at {new_spec_path}"
        old_spec = yaml.safe_load(old_spec_path.read_text(encoding="utf-8")) or {}
        new_spec = yaml.safe_load(new_spec_path.read_text(encoding="utf-8")) or {}
        return old_spec, new_spec, None

def impact_command(args: argparse.Namespace) -> int:
    from cairn_test.core.healing import ImpactAnalyzer
    from cairn_test.plugins.api.spec_diff import SpecDiffClassifier

    repo_root = Path(".")
    config = Config.load()
    old_spec, new_spec, err = _load_spec_pair(args, repo_root, config)
    if err or old_spec is None or new_spec is None:
        print(f"Error: {err or 'Specs required for impact analysis'}")
        return EXIT_CLI_ERROR

    tests_dir = Path(args.tests_dir or "tests")
    discovered = discover_tests(tests_dir)

    analyzer = ImpactAnalyzer(SpecDiffClassifier())
    affected = analyzer.find_affected_tests(discovered, old_spec, new_spec)

    if args.json:
        out = [
            {
                "test_id": a["test_id"],
                "touched_operations": a["touched_operations"],
                "changes": [
                    {"rule": c.rule_id, "kind": c.kind.value, "mechanism": c.mechanism.value, "detail": c.detail}
                    for c in a["changes"]
                ],
            }
            for a in affected
        ]
        print(json.dumps(out, indent=2))
    else:
        print(f"\ncairn-test impact: {len(affected)} of {len(discovered)} tests affected")
        print("=" * 60)
        for a in affected:
            print(f"AFFECTED {a['test_id']} (ops: {', '.join(a['touched_operations'])})")
            for c in a["changes"]:
                print(f"   -> [{c.kind.value.upper()}] {c.detail} ({c.mechanism.value})")
        print("=" * 60)

    return EXIT_PASS

def heal_command(args: argparse.Namespace) -> int:
    from cairn_test.core.healing import HealEngine, ImpactAnalyzer
    from cairn_test.plugins.api.spec_diff import SpecDiffClassifier

    repo_root = Path(".")
    config = Config.load()
    old_spec, new_spec, err = _load_spec_pair(args, repo_root, config)
    if err or old_spec is None or new_spec is None:
        print(f"Error: {err or 'Specs required for healing (--spec-diff OLD NEW or --old-spec, --new-spec)'}")
        return EXIT_CLI_ERROR

    tests_dir = Path(args.tests_dir or "tests")
    traces_dir = Path(args.traces_dir or "traces")
    discovered = discover_tests(tests_dir)

    analyzer = ImpactAnalyzer(SpecDiffClassifier())
    affected = analyzer.find_affected_tests(discovered, old_spec, new_spec)

    if args.id:
        target_ids = set(args.id.split(","))
        affected = [a for a in affected if a["test_id"] in target_ids]

    healer = HealEngine()
    proposals_count = 0
    proposals_list: list[dict[str, Any]] = []

    if not args.json:
        print(f"\ncairn-test heal: evaluating {len(affected)} affected tests")
        print("=" * 60)

    for item in affected:
        tid = item["test_id"]
        t_def = item["test_def"]
        tr_file = traces_dir / f"{tid}.trace.yaml"
        if not tr_file.is_file():
            continue
        tr_data = load_trace(tr_file)

        for change in item["changes"]:
            # 1. Healable changes
            if change.mechanism.value == "heal":
                p = healer.generate_heal_proposal(tid, t_def, tr_data, change, repo_root)
                if p:
                    if not args.json:
                        print(f"HEAL PROPOSAL: '{tid}' -> {change.detail}")
                    proposals_count += 1
                    proposals_list.append(p)
            # 2. Value request
            elif change.mechanism.value == "value-request":
                p = healer.generate_value_request(tid, change, repo_root)
                if p:
                    if not args.json:
                        print(f"VALUE REQUEST: '{tid}' -> {change.detail}")
                    proposals_count += 1
                    proposals_list.append(p)
            # 3. Expectation change suggestion
            elif change.mechanism.value == "expectation-change":
                p = healer.generate_expectation_change_suggestion(
                    tid, t_def, change.old_value or "", change.candidates, repo_root
                )
                if p:
                    if not args.json:
                        print(f"EXPECTATION SUGGESTION: '{tid}' -> {p['reason']}")
                    proposals_count += 1
                    proposals_list.append(p)

    if args.json:
        print(json.dumps({"proposals_created": proposals_count, "proposals": proposals_list}, indent=2))
    else:
        print("=" * 60)
        print(f"Generated {proposals_count} inert proposals in proposals/")
    return EXIT_PASS

def accept_observations_command(args: argparse.Namespace) -> int:
    from cairn_test.core.healing import accept_observations_batch

    repo_root = Path(".")
    props_dir = repo_root / "proposals"
    traces_dir = Path(args.traces_dir or "traces")

    # Look for proposal traces with observation-update kind
    observed_map = {}
    recorded_map = {}

    for p in props_dir.glob("*.trace.yaml"):
        test_id = p.name.replace(".trace.yaml", "")
        rec_p = traces_dir / f"{test_id}.trace.yaml"
        if rec_p.is_file():
            observed_map[test_id] = load_trace(p)
            recorded_map[test_id] = load_trace(rec_p)

    batch = accept_observations_batch(repo_root, observed_map, recorded_map)
    if args.json:
        print(json.dumps({"proposals_created": len(batch), "paths": [str(p) for p in batch]}, indent=2))
    else:
        print(f"Created {len(batch)} observation acceptance proposals in proposals/")
    return EXIT_PASS

def report_command(args: argparse.Namespace) -> int:
    from cairn_test.core.reporting import generate_html_report, generate_junit_xml

    store = EventStore(base_dir=".cairn-test")
    run_id = args.run_id

    # If run_id not provided, find the latest run_id from results
    if not run_id:
        import sqlite3
        with sqlite3.connect(store.db_path) as conn:
            row = conn.execute("SELECT run_id FROM results ORDER BY recorded_at DESC LIMIT 1").fetchone()
            if row:
                run_id = row[0]
            else:
                print("Error: No recorded runs found.")
                return EXIT_CLI_ERROR

    import sqlite3
    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM results WHERE run_id = ?", (run_id,)).fetchall()

    if not rows:
        print(f"Error: No results found for run '{run_id}'")
        return EXIT_CLI_ERROR

    test_verdicts = [dict(r) for r in rows]
    total = len(test_verdicts)
    passed = sum(1 for v in test_verdicts if v["outcome"] == "PASS")
    failed = sum(1 for v in test_verdicts if v["outcome"] == "FAIL")
    drifted = sum(1 for v in test_verdicts if v["outcome"] == "DRIFT")
    errored = sum(1 for v in test_verdicts if v["outcome"] == "ERROR")
    skipped = sum(1 for v in test_verdicts if v["outcome"] == "SKIPPED")

    run_summary = {
        "run_id": run_id,
        "total": total,
        "passed": passed,
        "failed": failed,
        "drifted": drifted,
        "errored": errored,
        "skipped": skipped,
        "outcome": "ERROR" if errored > 0 else ("FAIL" if failed > 0 else ("DRIFT" if drifted > 0 else "PASS")),
    }

    if args.junit:
        xml_str = generate_junit_xml(run_id, test_verdicts)
        p = Path(args.junit)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(xml_str, encoding="utf-8")
        print(f"Wrote JUnit report -> {p}")

    if args.html:
        html_str = generate_html_report(run_id, run_summary, test_verdicts)
        p = Path(args.html)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html_str, encoding="utf-8")
        print(f"Wrote HTML report -> {p}")

    if args.json:
        print(json.dumps({"run_summary": run_summary, "tests": test_verdicts}, indent=2))
    elif not args.junit and not args.html:
        print(f"\nRun Report: {run_id}")
        print("=" * 60)
        print(f"Total: {total} | Passed: {passed} | Failed: {failed} | Drifted: {drifted} | Errored: {errored} | Skipped: {skipped}")
        print("=" * 60)
        for v in test_verdicts:
            r_str = f" ({v['reason']})" if v.get("reason") else ""
            print(f"{v['outcome']:<8} {v['test_id']}{r_str}")

    return EXIT_PASS

def migrate_command(args: argparse.Namespace) -> int:
    from cairn_test.core.migration import MigrationEngine

    engine = MigrationEngine()
    target_dir = Path(args.dir or ".")
    results = engine.migrate_directory(target_dir, dry_run=args.dry_run)

    if args.json:
        out = [
            {
                "file": str(r.path),
                "kind": r.kind,
                "old_version": r.old_version,
                "new_version": r.new_version,
                "changes": r.changes,
            }
            for r in results
        ]
        print(json.dumps({"migrated_count": len(results), "files": out}, indent=2))
    else:
        mode_label = "[DRY RUN] " if args.dry_run else ""
        print(f"\n{mode_label}cairn-test migrate: {len(results)} files upgraded")
        print("=" * 60)
        for r in results:
            print(f"UPGRADED {r.path}: {r.old_version} -> {r.new_version}")
            for c in r.changes:
                print(f"  - {c}")
        print("=" * 60)

    return EXIT_PASS

def doctor_command(args: argparse.Namespace) -> int:
    from cairn_test.core.doctor import Doctor

    doc = Doctor()
    key_path = Path(args.key) if args.key else None
    checks = doc.run_all(key_path=key_path)

    all_ok = all(c.status == "OK" for c in checks)
    has_fail = any(c.status == "FAIL" for c in checks)

    if args.json:
        out = {
            "healthy": all_ok,
            "checks": [
                {
                    "id": c.id,
                    "name": c.name,
                    "status": c.status,
                    "message": c.message,
                    "remediation": c.remediation,
                }
                for c in checks
            ],
        }
        print(json.dumps(out, indent=2))
    else:
        print("\ncairn-test doctor: diagnostic results")
        print("=" * 60)
        for c in checks:
            badge = f"[{c.status}]"
            print(f"{badge:<8} {c.name}")
            print(f"         {c.message}")
            if c.remediation:
                print(f"         Remediation: {c.remediation}")
        print("=" * 60)

    return EXIT_ERROR if has_fail else EXIT_PASS

def status_command(args: argparse.Namespace) -> int:
    from cairn_test.core.health import HealthAnalyzer

    analyzer = HealthAnalyzer()
    health = analyzer.analyze()

    if args.json:
        out = {
            "total_tests": health.total_tests,
            "total_runs": health.total_runs,
            "drift_rate_percent": health.drift_rate_percent,
            "flaky_tests": health.flaky_tests,
            "quarantined_tests": health.quarantined_tests,
            "latest_outcomes": health.latest_outcomes,
        }
        print(json.dumps(out, indent=2))
    else:
        print("\ncairn-test status: Suite Health Overview")
        print("=" * 60)
        print(f"Total Tests in Suite: {health.total_tests}")
        print(f"Recorded Test Runs:   {health.total_runs}")
        print(f"Contract Drift Rate:  {health.drift_rate_percent}%")
        print(f"Flaky Tests ({len(health.flaky_tests)}):")
        for f in health.flaky_tests:
            print(f"  - {f}")
        print(f"Quarantined Tests ({len(health.quarantined_tests)}):")
        for q in health.quarantined_tests:
            print(f"  - {q['test_id']} ({q['reason']})")
        print("=" * 60)
        if health.total_tests == 0:
            props = list(Path("proposals").glob("*.proposal.yaml")) if Path("proposals").is_dir() else []
            if props:
                print(f"Tip: Found {len(props)} proposal(s) in proposals/. Run 'cairn-test draft --promote' to activate them.")

    return EXIT_PASS

def draft_command(args: argparse.Namespace) -> int:
    from cairn_test.core.draft import SpecDrafter, promote_drafts
    from cairn_test.plugins.api.spec import OpenAPISpec

    repo_root = Path(".")

    # Handle --promote
    if getattr(args, "promote", False):
        promoted = promote_drafts(repo_root)
        if getattr(args, "json", False):
            print(json.dumps({"promoted_count": len(promoted), "tests": [str(p) for p in promoted]}, indent=2))
        else:
            print(f"\ncairn-test draft: promoted {len(promoted)} draft proposals into tests/")
            print("=" * 60)
            for p in promoted:
                print(f"TEST -> {p}")
            print("=" * 60)
            print("Run 'cairn-test record' to record baseline observations for these tests.")
        return EXIT_PASS

    config = Config.load()
    spec_path = args.spec or config.spec
    if not spec_path or not Path(spec_path).is_file():
        print("Error: Spec file required for drafting (--spec openapi.yaml)")
        return EXIT_CLI_ERROR

    spec = OpenAPISpec.load(spec_path)
    drafter = SpecDrafter(spec)
    write_tests = getattr(args, "tests", False) or getattr(args, "out", "") == "tests"
    paths = drafter.draft_suite(repo_root, write_tests=write_tests)

    if args.json:
        key = "tests_created" if write_tests else "drafts_created"
        print(json.dumps({key: len(paths), "paths": [str(p) for p in paths]}, indent=2))
    else:
        dest_desc = "runnable tests in tests/" if write_tests else "draft proposals in proposals/"
        print(f"\ncairn-test draft: generated {len(paths)} {dest_desc}")
        print("=" * 60)
        for p in paths:
            prefix = "TEST" if write_tests else "DRAFT"
            print(f"{prefix} -> {p}")
        print("=" * 60)
        if not write_tests:
            print("To promote these draft proposals to runnable tests in tests/, run:")
            print("  cairn-test draft --promote")
            print("Or review them first with:")
            print("  cairn-test review")
    return EXIT_PASS

def plugin_command(args: argparse.Namespace) -> int:
    from cairn_test.core.pdk import scaffold_plugin
    action = getattr(args, "plugin_action", None)
    if action == "init":
        name = args.name
        target_dir = Path(args.dir) if getattr(args, "dir", None) else None
        res = scaffold_plugin(name, target_dir)
        if getattr(args, "json", False):
            print(json.dumps(res, indent=2))
        else:
            print(f"Scaffolded plugin '{res['plugin']}' in {res['directory']}")
            for f in res["files"]:
                print(f"  + {f}")
            print(f"\nRun verification with: python {res['directory']}/test_{res['plugin']}_plugin.py")
        return EXIT_PASS
    print("Unknown plugin action. Use 'cairn-test plugin init <name>'", file=sys.stderr)
    return EXIT_CLI_ERROR

def tutorial_command(args: argparse.Namespace) -> int:
    from cairn_test.tutorial import run_tutorial
    interactive = not getattr(args, "non_interactive", False)
    custom_dir = Path(args.dir) if getattr(args, "dir", None) else None
    return run_tutorial(interactive=interactive, custom_dir=custom_dir)

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

    # draft command
    draft_parser = subparsers.add_parser("draft", help="Deterministically draft baseline tests from OpenAPI spec")
    draft_parser.add_argument("--spec", type=str, help="Path to OpenAPI spec")
    draft_parser.add_argument("--tests", action="store_true", help="Write runnable test definitions directly into tests/")
    draft_parser.add_argument("--promote", action="store_true", help="Promote existing draft proposals from proposals/ into tests/")
    draft_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

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
    run_parser.add_argument("--changed", action="store_true", help="Run only tests affected by spec diff")
    run_parser.add_argument("--spec-diff", nargs=2, metavar=("OLD", "NEW"), help="Paths to old and new OpenAPI specs")
    run_parser.add_argument("--old-spec", type=str, help="Old OpenAPI spec path")
    run_parser.add_argument("--new-spec", type=str, help="New OpenAPI spec path")
    run_parser.add_argument("--junit", type=str, help="Export test results to JUnit XML file")
    run_parser.add_argument("--html", type=str, help="Export test results to static HTML report")

    # record command
    rec_parser = subparsers.add_parser("record", help="Record traces for tests as inert proposals")
    rec_parser.add_argument("target", nargs="?", default=None, help="Path to test file (e.g. tests/sample.test.yaml), draft ID, or test ID")
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
    rev_parser.add_argument("--id", dest="id_flag", type=str, help="Optional test ID to review")
    rev_parser.add_argument("--tests-dir", type=str, default="tests", help="Directory containing test files")
    rev_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # approve command
    appr_parser = subparsers.add_parser("approve", help="Sign cryptographic approval for a test")
    appr_parser.add_argument("id", nargs="?", type=str, help="Test ID to approve")
    appr_parser.add_argument("--id", dest="id_flag", type=str, help="Test ID to approve")
    appr_parser.add_argument("--key", type=str, help="Path to OpenSSH private key")
    appr_parser.add_argument("--identity", type=str, help="Signer identity / name")
    appr_parser.add_argument("--labels", type=str, help="Extra review labels (comma-separated)")

    # verify command
    ver_parser = subparsers.add_parser("verify", help="Verify cryptographic approvals in strict mode")
    ver_parser.add_argument("id", nargs="?", type=str, help="Optional test ID to verify")
    ver_parser.add_argument("--id", dest="id_flag", type=str, help="Optional test ID to verify")
    ver_parser.add_argument("--env", type=str, help="Target environment profile")
    ver_parser.add_argument("--tests-dir", type=str, default="tests", help="Directory containing test files")
    ver_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # impact command
    impact_parser = subparsers.add_parser("impact", help="Impact analysis on tests touching modified spec operations")
    impact_parser.add_argument("--spec-diff", nargs="+", metavar="SPEC", help="Path(s) to spec: [NEW] (diffed against git HEAD) or [OLD NEW]")
    impact_parser.add_argument("--old-spec", type=str, help="Path to old OpenAPI spec")
    impact_parser.add_argument("--new-spec", type=str, help="Path to new OpenAPI spec")
    impact_parser.add_argument("--tests-dir", type=str, default="tests", help="Directory containing test files")
    impact_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # heal command
    heal_parser = subparsers.add_parser("heal", help="Generate deterministic heal proposals for breaking spec changes")
    heal_parser.add_argument("--spec-diff", nargs="+", metavar="SPEC", help="Path(s) to spec: [NEW] (diffed against git HEAD) or [OLD NEW]")
    heal_parser.add_argument("--old-spec", type=str, help="Path to old OpenAPI spec")
    heal_parser.add_argument("--new-spec", type=str, help="Path to new OpenAPI spec")
    heal_parser.add_argument("--id", type=str, help="Specific test ID(s) to heal (comma-separated)")
    heal_parser.add_argument("--tests-dir", type=str, default="tests", help="Directory containing test files")
    heal_parser.add_argument("--traces-dir", type=str, default="traces", help="Directory containing trace files")
    heal_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # accept-observations command
    accept_obs_parser = subparsers.add_parser("accept-observations", help="Create batch proposals for additive observation diffs")
    accept_obs_parser.add_argument("--traces-dir", type=str, default="traces", help="Directory containing recorded traces")
    accept_obs_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # explain command
    explain_parser = subparsers.add_parser("explain", help="Explain test outcome from stored artifacts")
    explain_parser.add_argument("run_id", type=str, help="Run ID")
    explain_parser.add_argument("test_id", type=str, help="Test ID")
    explain_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # report command
    report_parser = subparsers.add_parser("report", help="Generate HTML and JUnit reports from stored run events")
    report_parser.add_argument("--run", dest="run_id", type=str, help="Run ID (defaults to latest run)")
    report_parser.add_argument("--junit", type=str, help="Output path for JUnit XML")
    report_parser.add_argument("--html", type=str, help="Output path for static HTML")
    report_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # migrate command
    migrate_parser = subparsers.add_parser("migrate", help="Upgrade stored test/trace files across schema versions")
    migrate_parser.add_argument("--dir", type=str, default=".", help="Directory to scan and migrate")
    migrate_parser.add_argument("--dry-run", action="store_true", help="Show proposed changes without writing")
    migrate_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # doctor command
    doctor_parser = subparsers.add_parser("doctor", help="Check security, key-type, and strict-mode assumptions")
    doctor_parser.add_argument("--key", type=str, help="Path to OpenSSH private key")
    doctor_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # status command
    status_parser = subparsers.add_parser("status", help="Display test suite health, flakiness, and drift rate")
    status_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # plugin command (PDK)
    plugin_parser = subparsers.add_parser("plugin", help="Plugin Developer Kit (PDK) utilities")
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_action", required=True)
    plugin_init = plugin_sub.add_parser("init", help="Scaffold a new domain-neutral plugin")
    plugin_init.add_argument("name", type=str, help="Name of the plugin (e.g. grpc, kafka, sql)")
    plugin_init.add_argument("--dir", type=str, help="Target directory for scaffolded plugin")
    plugin_init.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # tutorial command (T8.1)
    tutorial_parser = subparsers.add_parser("tutorial", help="Interactive onboarding tutorial")
    tutorial_parser.add_argument("--non-interactive", action="store_true", help="Run continuously without user prompts")
    tutorial_parser.add_argument("--dir", type=str, help="Directory for tutorial workspace")

    parsed = parser.parse_args()
    if parsed.command == "init":
        code = init_command(parsed)
        sys.exit(code)
    elif parsed.command == "draft":
        code = draft_command(parsed)
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
    elif parsed.command == "impact":
        code = impact_command(parsed)
        sys.exit(code)
    elif parsed.command == "heal":
        code = heal_command(parsed)
        sys.exit(code)
    elif parsed.command == "accept-observations":
        code = accept_observations_command(parsed)
        sys.exit(code)
    elif parsed.command == "explain":
        code = explain_command(parsed)
        sys.exit(code)
    elif parsed.command == "report":
        code = report_command(parsed)
        sys.exit(code)
    elif parsed.command == "migrate":
        code = migrate_command(parsed)
        sys.exit(code)
    elif parsed.command == "doctor":
        code = doctor_command(parsed)
        sys.exit(code)
    elif parsed.command == "status":
        code = status_command(parsed)
        sys.exit(code)
    elif parsed.command == "plugin":
        code = plugin_command(parsed)
        sys.exit(code)
    elif parsed.command == "tutorial":
        code = tutorial_command(parsed)
        sys.exit(code)

if __name__ == "__main__":
    main()
