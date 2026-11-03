"""
Reporting engine for cairn-test (T5.1, T5.2, FR-O1, FR-O5).
Generates:
1. Standard JUnit XML export (testsuites, testcase, failures, errors, skipped).
2. Clean, standalone, responsive static HTML run report.
"""

from __future__ import annotations
from datetime import datetime, timezone
import html
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

def generate_junit_xml(
    run_id: str,
    test_verdicts: list[dict[str, Any]],
    suite_name: str = "cairn-test",
    timestamp: str | None = None,
) -> str:
    """
    Generates standard JUnit XML string from test verdicts (T5.2, FR-O5).
    """
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    total = len(test_verdicts)
    failures = sum(1 for v in test_verdicts if v.get("outcome") in ("FAIL", "DRIFT"))
    errors = sum(1 for v in test_verdicts if v.get("outcome") == "ERROR")
    skipped = sum(1 for v in test_verdicts if v.get("outcome") == "SKIPPED")
    total_time = sum(v.get("duration_ms", 0.0) for v in test_verdicts) / 1000.0

    root = ET.Element(
        "testsuites",
        name=suite_name,
        time=f"{total_time:.3f}",
        tests=str(total),
        failures=str(failures),
        errors=str(errors),
    )

    suite = ET.SubElement(
        root,
        "testsuite",
        name=run_id,
        tests=str(total),
        failures=str(failures),
        errors=str(errors),
        skipped=str(skipped),
        time=f"{total_time:.3f}",
        timestamp=ts,
    )

    for item in test_verdicts:
        tid = item.get("test_id", "unknown")
        dur_s = item.get("duration_ms", 0.0) / 1000.0
        outcome = item.get("outcome", "PASS")
        reason = item.get("reason", "") or ""

        tc = ET.SubElement(
            suite,
            "testcase",
            name=tid,
            classname=f"{suite_name}.{tid}",
            time=f"{dur_s:.3f}",
        )

        if outcome == "FAIL":
            f_el = ET.SubElement(tc, "failure", message=reason or "Test failed behavioral expectations", type="BehavioralFailure")
            f_el.text = reason
        elif outcome == "DRIFT":
            f_el = ET.SubElement(tc, "failure", message=reason or "Test experienced contract drift", type="ContractDrift")
            f_el.text = f"Contract Drift: {reason}"
        elif outcome == "ERROR":
            e_el = ET.SubElement(tc, "error", message=reason or "Test execution encountered error", type="ExecutionError")
            e_el.text = reason
        elif outcome == "SKIPPED":
            s_el = ET.SubElement(tc, "skipped", message=reason or "Test was skipped")
            s_el.text = reason

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")

def generate_html_report(
    run_id: str,
    run_summary: dict[str, Any],
    test_verdicts: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """
    Generates a responsive, standalone static HTML report (T5.1, FR-O1, FR-O5).
    Contains no external CDN scripts or fonts.
    """
    meta = metadata or {}
    env_name = meta.get("env_profile", "default")
    mode_str = meta.get("mode", "dev")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    total = run_summary.get("total", len(test_verdicts))
    passed = run_summary.get("passed", 0)
    failed = run_summary.get("failed", 0)
    drifted = run_summary.get("drifted", 0)
    errored = run_summary.get("errored", 0)
    skipped = run_summary.get("skipped", 0)
    overall_outcome = run_summary.get("outcome", "PASS")

    color_map = {
        "PASS": "#22c55e",
        "FAIL": "#ef4444",
        "DRIFT": "#f59e0b",
        "ERROR": "#a855f7",
        "SKIPPED": "#6b7280",
    }
    badge_color = color_map.get(overall_outcome, "#3b82f6")

    rows_html = []
    for item in test_verdicts:
        tid = html.escape(str(item.get("test_id", "")))
        outcome = item.get("outcome", "PASS")
        dur = f"{item.get('duration_ms', 0.0):.1f}ms"
        reason = html.escape(str(item.get("reason", "") or ""))
        c = color_map.get(outcome, "#6b7280")

        rows_html.append(f"""
        <tr>
            <td style="font-weight: 600;">{tid}</td>
            <td><span class="badge" style="background-color: {c};">{outcome}</span></td>
            <td>{dur}</td>
            <td style="color: #64748b; font-size: 0.9em;">{reason}</td>
        </tr>
        """)

    table_rows = "\n".join(rows_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>cairn-test Report - {html.escape(run_id)}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        body {{ background-color: #f8fafc; color: #1e293b; padding: 32px; }}
        .container {{ max-width: 1000px; margin: 0 auto; background: #ffffff; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); padding: 32px; }}
        header {{ border-bottom: 1px solid #e2e8f0; padding-bottom: 24px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; }}
        h1 {{ font-size: 24px; font-weight: 700; color: #0f172a; }}
        .meta {{ color: #64748b; font-size: 14px; margin-top: 4px; }}
        .badge {{ display: inline-block; padding: 4px 12px; border-radius: 9999px; color: #ffffff; font-weight: 600; font-size: 13px; text-transform: uppercase; }}
        .cards {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 32px; }}
        .card {{ background: #f1f5f9; padding: 16px; border-radius: 8px; text-align: center; }}
        .card .num {{ font-size: 28px; font-weight: 700; margin-top: 4px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
        th {{ background: #f8fafc; text-align: left; padding: 12px 16px; font-size: 12px; text-transform: uppercase; color: #64748b; border-bottom: 2px solid #e2e8f0; }}
        td {{ padding: 14px 16px; border-bottom: 1px solid #e2e8f0; font-size: 14px; }}
        tr:hover {{ background-color: #f8fafc; }}
        footer {{ margin-top: 32px; font-size: 12px; color: #94a3b8; text-align: center; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>cairn-test Run Report</h1>
                <div class="meta">Run ID: <strong>{html.escape(run_id)}</strong> | Env: <strong>{html.escape(env_name)}</strong> | Mode: <strong>{html.escape(mode_str)}</strong></div>
            </div>
            <div>
                <span class="badge" style="background-color: {badge_color}; font-size: 16px; padding: 6px 16px;">{overall_outcome}</span>
            </div>
        </header>

        <div class="cards">
            <div class="card"><div class="meta">TOTAL</div><div class="num" style="color: #334155;">{total}</div></div>
            <div class="card"><div class="meta">PASSED</div><div class="num" style="color: #22c55e;">{passed}</div></div>
            <div class="card"><div class="meta">FAILED</div><div class="num" style="color: #ef4444;">{failed}</div></div>
            <div class="card"><div class="meta">DRIFTED</div><div class="num" style="color: #f59e0b;">{drifted}</div></div>
            <div class="card"><div class="meta">ERRORED</div><div class="num" style="color: #a855f7;">{errored}</div></div>
            <div class="card"><div class="meta">SKIPPED</div><div class="num" style="color: #6b7280;">{skipped}</div></div>
        </div>

        <h2>Test Results</h2>
        <table>
            <thead>
                <tr>
                    <th>Test ID</th>
                    <th>Outcome</th>
                    <th>Duration</th>
                    <th>Reason / Details</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>

        <footer>Generated by cairn-test at {generated_at}</footer>
    </div>
</body>
</html>
"""
