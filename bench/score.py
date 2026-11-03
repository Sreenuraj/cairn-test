"""
Benchmark Scoring Script (T6.7, FR-B4, FR-B8).

Calculates:
1. Confusion matrix (Expected rows vs Actual columns) for:
   - Contract-only (must be 100% DRIFT)
   - Bug-only (must be 100% FAIL)
   - Benign (must be 100% PASS)
   - Compound (normative precedence: FAIL with drift detail, or blocked DRIFT)
2. Maintenance effort metrics:
   - Median triage time (with human review) for cairn-test vs Newman
   - Median fix time (with human review) for cairn-test vs Newman
   - Triage improvement percentage (must be >= 30% for E2)
3. Repair quality metrics:
   - False heals count (must be 0)
   - Masking suggestions count (must be 0)
   - Proposal acceptance rate
4. Authoring effort and execution speed
"""

from __future__ import annotations
import json
from pathlib import Path
import statistics
from typing import Any

from bench.timelog import TimeLogEntry

def calculate_confusion_matrix(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    matrix = {
        "PASS": {"PASS": 0, "FAIL": 0, "DRIFT": 0, "ERROR": 0},
        "FAIL": {"PASS": 0, "FAIL": 0, "DRIFT": 0, "ERROR": 0},
        "DRIFT": {"PASS": 0, "FAIL": 0, "DRIFT": 0, "ERROR": 0},
    }
    violations: list[str] = []

    for ev in evaluations:
        exp = ev["expected"]
        act = ev["actual"]
        seed = ev.get("seed_id", "unknown")
        test_id = ev.get("test_id", "unknown")

        if exp in matrix and act in matrix[exp]:
            matrix[exp][act] += 1

        if exp != act:
            violations.append(
                f"Classification mismatch in seed '{seed}' on test '{test_id}': expected {exp}, got {act}"
            )

        if ev.get("expect_drift_detail") and act == "FAIL" and not ev.get("has_drift_detail"):
            violations.append(
                f"Compound precedence violation in seed '{seed}' on test '{test_id}': FAIL missing drift detail"
            )

    total_evals = len(evaluations)
    correct_evals = total_evals - len([v for v in violations if "mismatch" in v])
    accuracy = (correct_evals / total_evals * 100.0) if total_evals > 0 else 0.0

    return {
        "matrix": matrix,
        "accuracy_pct": round(accuracy, 2),
        "total_evaluations": total_evals,
        "violations": violations,
        "passed": len(violations) == 0,
    }

def calculate_maintenance_metrics(entries: list[TimeLogEntry]) -> dict[str, Any]:
    cairn_triage: list[float] = []
    cairn_fix: list[float] = []
    cairn_review: list[float] = []

    newman_triage: list[float] = []
    newman_fix: list[float] = []
    newman_review: list[float] = []

    for e in entries:
        if e.tool == "cairn-test":
            cairn_triage.append(e.triage_time_s)
            cairn_fix.append(e.fix_time_s)
            cairn_review.append(e.review_time_s)
        elif e.tool == "newman":
            newman_triage.append(e.triage_time_s)
            newman_fix.append(e.fix_time_s)
            newman_review.append(e.review_time_s)

    cairn_med_triage = statistics.median(cairn_triage) if cairn_triage else 0.0
    cairn_med_fix = statistics.median(cairn_fix) if cairn_fix else 0.0
    cairn_med_review = statistics.median(cairn_review) if cairn_review else 0.0
    cairn_total_triage_fix = cairn_med_triage + cairn_med_fix + cairn_med_review

    newman_med_triage = statistics.median(newman_triage) if newman_triage else 0.0
    newman_med_fix = statistics.median(newman_fix) if newman_fix else 0.0
    newman_med_review = statistics.median(newman_review) if newman_review else 0.0
    newman_total_triage_fix = newman_med_triage + newman_med_fix + newman_med_review

    if newman_med_triage > 0:
        triage_improvement_pct = round(
            ((newman_med_triage - cairn_med_triage) / newman_med_triage) * 100.0, 2
        )
    else:
        triage_improvement_pct = 0.0

    if newman_total_triage_fix > 0:
        total_maintenance_reduction_pct = round(
            ((newman_total_triage_fix - cairn_total_triage_fix) / newman_total_triage_fix) * 100.0,
            2,
        )
    else:
        total_maintenance_reduction_pct = 0.0

    return {
        "cairn_test": {
            "median_triage_s": round(cairn_med_triage, 2),
            "median_fix_s": round(cairn_med_fix, 2),
            "median_review_s": round(cairn_med_review, 2),
            "median_total_maintenance_s": round(cairn_total_triage_fix, 2),
        },
        "newman": {
            "median_triage_s": round(newman_med_triage, 2),
            "median_fix_s": round(newman_med_fix, 2),
            "median_review_s": round(newman_med_review, 2),
            "median_total_maintenance_s": round(newman_total_triage_fix, 2),
        },
        "triage_improvement_pct": triage_improvement_pct,
        "total_maintenance_reduction_pct": total_maintenance_reduction_pct,
        "meets_triage_threshold": triage_improvement_pct >= 30.0,
    }

def calculate_repair_quality(repairs: list[dict[str, Any]]) -> dict[str, Any]:
    false_heals = sum(1 for r in repairs if r.get("is_false_heal"))
    masking_suggestions = sum(1 for r in repairs if r.get("is_masking"))
    total_proposals = sum(1 for r in repairs if r.get("proposal_generated"))
    accepted_proposals = sum(1 for r in repairs if r.get("proposal_accepted"))

    rate = (accepted_proposals / total_proposals * 100.0) if total_proposals > 0 else 100.0

    return {
        "false_heals": false_heals,
        "masking_suggestions": masking_suggestions,
        "total_proposals": total_proposals,
        "accepted_proposals": accepted_proposals,
        "acceptance_rate_pct": round(rate, 2),
        "zero_false_heals": false_heals == 0,
        "zero_masking_suggestions": masking_suggestions == 0,
    }

def format_score_report(summary: dict[str, Any]) -> str:
    cm = summary.get("confusion_matrix", {})
    matrix = cm.get("matrix", {})
    maint = summary.get("maintenance", {})
    rq = summary.get("repair_quality", {})

    lines = []
    lines.append("# Checkpoint E2 Benchmark Scoring Summary")
    lines.append("")
    lines.append("## 1. Classification Confusion Matrix")
    lines.append("| Expected \\ Actual | PASS | FAIL | DRIFT | ERROR |")
    lines.append("| :--- | :---: | :---: | :---: | :---: |")
    for exp_label in ["PASS", "FAIL", "DRIFT"]:
        row = matrix.get(exp_label, {})
        lines.append(
            f"| **{exp_label}** | {row.get('PASS', 0)} | {row.get('FAIL', 0)} | {row.get('DRIFT', 0)} | {row.get('ERROR', 0)} |"
        )
    lines.append("")
    lines.append(f"- **Classification Accuracy**: {cm.get('accuracy_pct', 0.0)}%")
    lines.append(f"- **Violations**: {len(cm.get('violations', []))}")
    lines.append("")
    lines.append("## 2. Maintenance Efficiency (cairn-test vs Newman)")
    lines.append("| Metric | cairn-test | Newman | Improvement |")
    lines.append("| :--- | :---: | :---: | :---: |")
    ct = maint.get("cairn_test", {})
    nm = maint.get("newman", {})
    lines.append(f"| Median Triage Time | {ct.get('median_triage_s', 0)}s | {nm.get('median_triage_s', 0)}s | **{maint.get('triage_improvement_pct', 0)}%** (threshold: >= 30%) |")
    lines.append(f"| Median Fix Time | {ct.get('median_fix_s', 0)}s | {nm.get('median_fix_s', 0)}s | - |")
    lines.append(f"| Median Review Time | {ct.get('median_review_s', 0)}s | {nm.get('median_review_s', 0)}s | - |")
    lines.append(f"| Total Maintenance | {ct.get('median_total_maintenance_s', 0)}s | {nm.get('median_total_maintenance_s', 0)}s | **{maint.get('total_maintenance_reduction_pct', 0)}%** |")
    lines.append("")
    lines.append("## 3. Repair Quality & Safety")
    lines.append(f"- **False Heals**: {rq.get('false_heals', 0)} (must be 0: {'PASS' if rq.get('zero_false_heals') else 'FAIL'})")
    lines.append(f"- **Masking Suggestions**: {rq.get('masking_suggestions', 0)} (must be 0: {'PASS' if rq.get('zero_masking_suggestions') else 'FAIL'})")
    lines.append(f"- **Proposal Acceptance Rate**: {rq.get('acceptance_rate_pct', 0)}%")
    lines.append("")
    lines.append("## 4. E2 Kill Criteria Decision")
    pass_triage = maint.get("meets_triage_threshold", False)
    pass_safety = rq.get("zero_false_heals", False) and rq.get("zero_masking_suggestions", False)
    pass_class = cm.get("passed", False)

    e2_passed = pass_triage and pass_safety and pass_class
    lines.append(f"- Triage >= 30% lower than Newman: {'PASS' if pass_triage else 'FAIL'}")
    lines.append(f"- Zero false heals & zero masking suggestions: {'PASS' if pass_safety else 'FAIL'}")
    lines.append(f"- 100% correct classification: {'PASS' if pass_class else 'FAIL'}")
    lines.append(f"- **Overall Checkpoint E2 Status**: {'GO / PASSED' if e2_passed else 'NO-GO / FAILED'}")

    return "\n".join(lines)
