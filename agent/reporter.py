"""Report generator: converts run artifacts into comprehensive report.md and report.html."""

from datetime import datetime
import html
import json
from pathlib import Path
from typing import Any, Optional

from agent.models import (
    Finding,
    FirmwareAnalysis,
    RunManifest,
    TestCase,
    TestResult,
)


def _compute_coverage(
    tests: list[TestCase],
    results: list[TestResult],
) -> dict[str, dict[str, int]]:
    """Compute test category coverage counts and pass rates."""
    res_map = {r.test_id: r.status for r in results}
    coverage: dict[str, dict[str, int]] = {}

    for t in tests:
        cat = t.category
        if cat not in coverage:
            coverage[cat] = {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "errors": 0,
            }
        coverage[cat]["total"] += 1
        status = res_map.get(t.id, "NOT_RUN")
        if status == "PASS":
            coverage[cat]["passed"] += 1
        elif status == "FAIL":
            coverage[cat]["failed"] += 1
        elif status == "ERROR":
            coverage[cat]["errors"] += 1

    return coverage


def _extract_source_snippet(
    source_code: str,
    lines: list[int],
    context: int = 2,
) -> str:
    """Extract source lines with surrounding context."""
    if not source_code or not lines:
        return ""
    all_lines = source_code.splitlines()
    min_line = max(1, min(lines) - context)
    max_line = min(len(all_lines), max(lines) + context)

    snippet_lines = []
    for i in range(min_line, max_line + 1):
        marker = ">>" if i in lines else "  "
        snippet_lines.append(f"{marker} {i:3d} | {all_lines[i - 1]}")
    return "\n".join(snippet_lines)


def build_markdown_report(
    manifest: RunManifest,
    tests: list[TestCase],
    results: list[TestResult],
    findings: list[Finding],
    analysis: Optional[FirmwareAnalysis] = None,
    source_code: str = "",
) -> str:
    """Generate GitHub-flavored Markdown test report."""
    pass_pct = (
        f"{(manifest.passed / manifest.total_tests * 100):.1f}%"
        if manifest.total_tests
        else "0%"
    )
    coverage = _compute_coverage(tests, results)
    test_map = {t.id: t for t in tests}

    md = []
    md.append(f"# FirmAgent Autonomous Test Report")
    md.append(
        f"**Run ID**: `{manifest.run_id}` | **Firmware**: `{manifest.firmware_name}` | **Status**: `{manifest.status.upper()}`\n"
    )
    md.append(
        f"- **Started**: {manifest.started_at}\n- **Finished**: {manifest.finished_at or 'In Progress'}\n"
    )

    # Executive Summary / Metric Cards
    md.append("## Executive Summary\n")
    md.append("| Metric | Count | Rate |")
    md.append("| :--- | :--- | :--- |")
    md.append(f"| **Total Tests** | {manifest.total_tests} | 100% |")
    md.append(f"| **Passed** | {manifest.passed} | {pass_pct} |")
    md.append(f"| **Failed** | {manifest.failed} | - |")
    md.append(f"| **Errors** | {manifest.errors} | - |")
    md.append(f"| **Bugs / Findings** | {len(findings)} | - |\n")

    # Coverage Matrix
    md.append("## Test Coverage Matrix\n")
    md.append(
        "| Category | Total Tests | Passed | Failed | Errors | Pass Rate |"
    )
    md.append("| :--- | :---: | :---: | :---: | :---: | :---: |")
    for cat, counts in sorted(coverage.items()):
        rate = (
            f"{(counts['passed'] / counts['total'] * 100):.1f}%"
            if counts["total"]
            else "0%"
        )
        md.append(
            f"| `{cat}` | {counts['total']} | {counts['passed']} | {counts['failed']} | {counts['errors']} | {rate} |"
        )
    md.append("")

    # Root Cause Findings
    md.append("## Root-Cause Findings & Planted Bugs\n")
    if not findings:
        md.append(
            "> [!NOTE]\n> No software defects or failures were identified in this run.\n"
        )
    else:
        for f in findings:
            sev_badge = f.severity.upper()
            md.append(f"### [{f.id}] {f.title}")
            md.append(
                f"- **Severity**: `{sev_badge}` | **Spec Rule**: `{f.spec_ref or 'General'}`"
            )
            md.append(
                f"- **Failed Tests**: {', '.join(f'`{tid}`' for tid in f.failed_tests)}"
            )
            md.append(f"- **Expected Behavior**: {f.expected}")
            md.append(f"- **Observed Behavior**: {f.observed}")
            md.append(f"- **Likely Cause**: {f.likely_cause}")

            if f.suspect_lines:
                md.append(
                    f"- **Suspect Line(s)**: {', '.join(str(l) for l in f.suspect_lines)}"
                )
                if source_code:
                    snippet = _extract_source_snippet(
                        source_code, f.suspect_lines
                    )
                    if snippet:
                        md.append(f"```cpp\n{snippet}\n```")

            md.append(f"- **Suggested Fix**:")
            md.append(f"```cpp\n{f.suggested_fix}\n```\n")

    # Test Execution Table
    md.append("## Test Execution Details\n")
    md.append(
        "| ID | Test Name | Category | Status | Duration | Observed Serial Summary |"
    )
    md.append("| :--- | :--- | :--- | :---: | :---: | :--- |")
    for r in results:
        t = test_map.get(r.test_id)
        name = t.name if t else r.test_id
        cat = t.category if t else "-"
        status_icon = (
            "PASS"
            if r.status == "PASS"
            else ("FAIL" if r.status == "FAIL" else "ERROR")
        )
        obs_sample = (
            "; ".join(r.observed_lines[:3])
            if r.observed_lines
            else (r.error_message or "none")
        )
        if len(obs_sample) > 50:
            obs_sample = obs_sample[:47] + "..."
        md.append(
            f"| `{r.test_id}` | {name} | `{cat}` | **{status_icon}** | {r.duration_s:.1f}s | `{obs_sample}` |"
        )
    md.append("")

    # Spec Rules Reference
    if analysis and analysis.spec_rules:
        md.append("## Specification Oracle Reference\n")
        for rule in analysis.spec_rules:
            src_str = (
                f" *(lines: {rule.source_lines})*" if rule.source_lines else ""
            )
            md.append(f"- **{rule.id}**: {rule.text}{src_str}")
        md.append("")

    return "\n".join(md)


def build_html_report(
    manifest: RunManifest,
    tests: list[TestCase],
    results: list[TestResult],
    findings: list[Finding],
    analysis: Optional[FirmwareAnalysis] = None,
    source_code: str = "",
) -> str:
    """Generate standalone dark-themed HTML test report with embedded CSS."""
    pass_pct = (
        (manifest.passed / manifest.total_tests * 100)
        if manifest.total_tests
        else 0
    )
    coverage = _compute_coverage(tests, results)
    test_map = {t.id: t for t in tests}

    # Format Coverage Rows
    coverage_rows = []
    for cat, counts in sorted(coverage.items()):
        c_pct = (
            (counts["passed"] / counts["total"] * 100)
            if counts["total"]
            else 0
        )
        bar_color = (
            "#22C55E"
            if c_pct == 100
            else ("#EF4444" if c_pct == 0 else "#F59E0B")
        )
        coverage_rows.append(
            f"""
            <tr>
                <td><span class="badge badge-cat">{html.escape(cat)}</span></td>
                <td><strong>{counts['total']}</strong></td>
                <td style="color: #22C55E;">{counts['passed']}</td>
                <td style="color: #EF4444;">{counts['failed']}</td>
                <td style="color: #F59E0B;">{counts['errors']}</td>
                <td style="width: 140px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <div class="progress-track">
                            <div class="progress-fill" style="width: {c_pct:.1f}%; background: {bar_color};"></div>
                        </div>
                        <span style="font-size: 12px; min-width: 40px;">{c_pct:.0f}%</span>
                    </div>
                </td>
            </tr>
        """
        )

    # Format Finding Cards
    finding_cards = []
    if not findings:
        finding_cards.append(
            """
            <div class="card" style="border-left: 4px solid #22C55E;">
                <p style="color: #22C55E; margin: 0; font-weight: 600;">✓ No software defects or failures identified in this run.</p>
            </div>
        """
        )
    else:
        for f in findings:
            sev = f.severity.lower()
            sev_class = (
                "badge-high"
                if sev == "high"
                else ("badge-med" if sev == "medium" else "badge-low")
            )
            spec_badge = (
                f'<span class="badge badge-cat">Spec {html.escape(f.spec_ref)}</span>'
                if f.spec_ref
                else ""
            )

            tests_badges = " ".join(
                f'<span class="badge badge-fail">{html.escape(tid)}</span>'
                for tid in f.failed_tests
            )

            snippet_block = ""
            if f.suspect_lines and source_code:
                snippet = _extract_source_snippet(
                    source_code, f.suspect_lines
                )
                if snippet:
                    snippet_block = f"""
                    <div style="margin-top: 8px;">
                        <span class="subhead">Source Snippet (Suspect Lines {f.suspect_lines}):</span>
                        <pre><code>{html.escape(snippet)}</code></pre>
                    </div>
                    """

            finding_cards.append(
                f"""
            <div class="card finding-card">
                <div class="card-header">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <span class="badge {sev_class}">{html.escape(f.severity.upper())}</span>
                        <h3 style="margin: 0; font-size: 16px;">{html.escape(f.id)}: {html.escape(f.title)}</h3>
                    </div>
                    <div>{spec_badge}</div>
                </div>
                <div style="margin: 12px 0;">
                    <span class="subhead">Failed Tests:</span> {tests_badges}
                </div>
                <div class="compare-grid">
                    <div class="compare-box compare-exp">
                        <span class="subhead" style="color: #22C55E;">Expected:</span>
                        <div>{html.escape(f.expected)}</div>
                    </div>
                    <div class="compare-box compare-obs">
                        <span class="subhead" style="color: #EF4444;">Observed:</span>
                        <div>{html.escape(f.observed)}</div>
                    </div>
                </div>
                <div style="margin-top: 12px;">
                    <span class="subhead">Likely Root Cause:</span>
                    <p style="margin: 4px 0 0 0; color: #E2E8F0;">{html.escape(f.likely_cause)}</p>
                </div>
                {snippet_block}
                <div style="margin-top: 12px;">
                    <span class="subhead">Suggested Fix:</span>
                    <pre><code>{html.escape(f.suggested_fix)}</code></pre>
                </div>
            </div>
            """
            )

    # Format Results Table Rows
    results_rows = []
    for r in results:
        t = test_map.get(r.test_id)
        name = t.name if t else r.test_id
        cat = t.category if t else "-"
        status_badge = (
            f'<span class="badge badge-pass">✓ PASS</span>'
            if r.status == "PASS"
            else (
                f'<span class="badge badge-fail">✗ FAIL</span>'
                if r.status == "FAIL"
                else f'<span class="badge badge-err">⚠ ERROR</span>'
            )
        )

        obs_html = "<br>".join(
            html.escape(line) for line in r.observed_lines[:3]
        )
        if len(r.observed_lines) > 3:
            obs_html += f"<br><span style='color:#94A3B8;'>... +{len(r.observed_lines) - 3} more lines</span>"
        if not obs_html and r.error_message:
            obs_html = (
                f"<span style='color:#EF4444;'>{html.escape(r.error_message)}</span>"
            )

        results_rows.append(
            f"""
            <tr>
                <td><strong>{html.escape(r.test_id)}</strong></td>
                <td>{html.escape(name)}</td>
                <td><span class="badge badge-cat">{html.escape(cat)}</span></td>
                <td>{status_badge}</td>
                <td>{r.duration_s:.1f}s</td>
                <td style="font-family: monospace; font-size: 12px;">{obs_html}</td>
            </tr>
        """
        )

    # HTML Document Template
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FirmAgent Report - {html.escape(manifest.run_id)}</title>
    <style>
        :root {{
            --bg: #0F172A;
            --surface: #1E293B;
            --surface-subtle: #243044;
            --border: #334155;
            --text: #E2E8F0;
            --muted: #94A3B8;
            --accent: #6366F1;
            --pass: #22C55E;
            --fail: #EF4444;
            --warn: #F59E0B;
        }}
        body {{
            background-color: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            margin: 0;
            padding: 32px 24px;
            line-height: 1.5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 20px;
            margin-bottom: 24px;
        }}
        .header h1 {{
            margin: 0 0 6px 0;
            font-size: 26px;
            font-weight: 700;
            letter-spacing: -0.5px;
            color: #F8FAFC;
        }}
        .badge {{
            display: inline-block;
            padding: 3px 8px;
            font-size: 11px;
            font-weight: 600;
            border-radius: 6px;
            text-transform: uppercase;
        }}
        .badge-pass {{ background: rgba(34, 197, 94, 0.15); color: #22C55E; border: 1px solid rgba(34, 197, 94, 0.3); }}
        .badge-fail {{ background: rgba(239, 68, 68, 0.15); color: #EF4444; border: 1px solid rgba(239, 68, 68, 0.3); }}
        .badge-err  {{ background: rgba(245, 158, 11, 0.15); color: #F59E0B; border: 1px solid rgba(245, 158, 11, 0.3); }}
        .badge-cat  {{ background: var(--surface-subtle); color: var(--muted); border: 1px solid var(--border); }}
        .badge-high {{ background: rgba(239, 68, 68, 0.2); color: #EF4444; border: 1px solid #EF4444; }}
        .badge-med  {{ background: rgba(245, 158, 11, 0.2); color: #F59E0B; border: 1px solid #F59E0B; }}
        .badge-low  {{ background: rgba(99, 102, 241, 0.2); color: #818CF8; border: 1px solid #818CF8; }}

        /* Metrics grid */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 28px;
        }}
        .metric-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px 20px;
        }}
        .metric-label {{
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--muted);
            margin-bottom: 6px;
        }}
        .metric-value {{
            font-size: 28px;
            font-weight: 700;
            color: #F8FAFC;
        }}

        .card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 24px;
        }}
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 12px;
            margin-bottom: 16px;
        }}
        .section-title {{
            font-size: 18px;
            font-weight: 600;
            margin: 0 0 16px 0;
            color: #F8FAFC;
        }}
        .subhead {{
            font-size: 11px;
            font-weight: 600;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        th, td {{
            text-align: left;
            padding: 10px 14px;
            border-bottom: 1px solid var(--border);
        }}
        th {{
            color: var(--muted);
            font-weight: 600;
            background: rgba(15, 23, 42, 0.4);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        tr:hover td {{
            background: var(--surface-subtle);
        }}

        .progress-track {{
            width: 100%;
            height: 6px;
            background: var(--surface-subtle);
            border-radius: 3px;
            overflow: hidden;
        }}
        .progress-fill {{
            height: 100%;
            border-radius: 3px;
        }}

        /* Findings */
        .finding-card {{
            border-left: 4px solid var(--accent);
            margin-bottom: 16px;
        }}
        .compare-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-top: 8px;
        }}
        .compare-box {{
            padding: 12px;
            border-radius: 8px;
            font-size: 13px;
        }}
        .compare-exp {{ background: rgba(34, 197, 94, 0.08); border: 1px solid rgba(34, 197, 94, 0.2); }}
        .compare-obs {{ background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.2); }}

        pre {{
            background: #090E1A;
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 12px;
            overflow-x: auto;
            font-size: 12px;
            font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
            color: #E2E8F0;
            margin: 6px 0 0 0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <div>
                <h1>FirmAgent Autonomous Test Report</h1>
                <div style="color: var(--muted); font-size: 13px;">
                    Firmware: <strong style="color: #F8FAFC;">{html.escape(manifest.firmware_name)}</strong> &nbsp;|&nbsp;
                    Run ID: <code>{html.escape(manifest.run_id)}</code> &nbsp;|&nbsp;
                    Status: <strong style="color: {'#22C55E' if manifest.status == 'done' else '#EF4444'};">{html.escape(manifest.status.upper())}</strong>
                </div>
            </div>
            <div style="text-align: right; color: var(--muted); font-size: 12px;">
                Started: {html.escape(manifest.started_at)}<br>
                Finished: {html.escape(manifest.finished_at or "In progress")}
            </div>
        </div>

        <!-- Metric Cards -->
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">Total Tests</div>
                <div class="metric-value">{manifest.total_tests}</div>
            </div>
            <div class="metric-card" style="border-top: 3px solid #22C55E;">
                <div class="metric-label">Passed</div>
                <div class="metric-value" style="color: #22C55E;">{manifest.passed} <span style="font-size: 14px; font-weight: normal;">({pass_pct:.0f}%)</span></div>
            </div>
            <div class="metric-card" style="border-top: 3px solid #EF4444;">
                <div class="metric-label">Failed</div>
                <div class="metric-value" style="color: #EF4444;">{manifest.failed}</div>
            </div>
            <div class="metric-card" style="border-top: 3px solid #F59E0B;">
                <div class="metric-label">Errors</div>
                <div class="metric-value" style="color: #F59E0B;">{manifest.errors}</div>
            </div>
            <div class="metric-card" style="border-top: 3px solid #6366F1;">
                <div class="metric-label">Defects Identified</div>
                <div class="metric-value" style="color: #818CF8;">{len(findings)}</div>
            </div>
        </div>

        <!-- Coverage Matrix -->
        <div class="card">
            <h2 class="section-title">Test Coverage by Category</h2>
            <table>
                <thead>
                    <tr>
                        <th>Category</th>
                        <th>Total</th>
                        <th>Passed</th>
                        <th>Failed</th>
                        <th>Errors</th>
                        <th>Pass Rate</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(coverage_rows)}
                </tbody>
            </table>
        </div>

        <!-- Root Cause Findings -->
        <div class="card">
            <h2 class="section-title">Root-Cause Analysis & Identified Bugs ({len(findings)})</h2>
            {''.join(finding_cards)}
        </div>

        <!-- Detailed Results Table -->
        <div class="card">
            <h2 class="section-title">Execution Details ({len(results)} tests)</h2>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Test Name</th>
                        <th>Category</th>
                        <th>Status</th>
                        <th>Duration</th>
                        <th>Observed Serial Telemetry</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(results_rows)}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""


def generate_reports(
    run_dir: Path | str,
    firmware_source_path: Path | str | None = None,
) -> tuple[Path, Path]:
    """Load run artifacts from run_dir, generate report.md and report.html."""
    dir_path = Path(run_dir)
    manifest_file = dir_path / "manifest.json"
    results_file = dir_path / "results.json"
    tests_file = dir_path / "tests.json"
    findings_file = dir_path / "findings.json"
    analysis_file = dir_path / "analysis.json"

    if not manifest_file.is_file():
        raise FileNotFoundError(f"manifest.json not found in {run_dir}")
    if not results_file.is_file():
        raise FileNotFoundError(f"results.json not found in {run_dir}")
    if not tests_file.is_file():
        raise FileNotFoundError(f"tests.json not found in {run_dir}")

    manifest_raw = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest = RunManifest.model_validate(manifest_raw)

    results_raw = json.loads(results_file.read_text(encoding="utf-8"))
    results = [TestResult.model_validate(r) for r in results_raw]

    tests_raw = json.loads(tests_file.read_text(encoding="utf-8"))
    tests_list = (
        tests_raw.get("tests", [])
        if isinstance(tests_raw, dict)
        else tests_raw
    )
    tests = [TestCase.model_validate(t) for t in tests_list]

    findings: list[Finding] = []
    if findings_file.is_file():
        findings_raw = json.loads(findings_file.read_text(encoding="utf-8"))
        findings = [Finding.model_validate(f) for f in findings_raw]

    analysis: Optional[FirmwareAnalysis] = None
    if analysis_file.is_file():
        analysis_raw = json.loads(analysis_file.read_text(encoding="utf-8"))
        analysis = FirmwareAnalysis.model_validate(analysis_raw)

    source_code = ""
    source_candidates = [
        firmware_source_path,
        dir_path / "firmware_source.txt",
        Path("firmware/fan_controller/src/main.cpp"),
    ]
    for cand in source_candidates:
        if cand and Path(cand).is_file():
            source_code = Path(cand).read_text(encoding="utf-8")
            break

    # Build reports
    md_content = build_markdown_report(
        manifest=manifest,
        tests=tests,
        results=results,
        findings=findings,
        analysis=analysis,
        source_code=source_code,
    )
    html_content = build_html_report(
        manifest=manifest,
        tests=tests,
        results=results,
        findings=findings,
        analysis=analysis,
        source_code=source_code,
    )

    report_md_path = dir_path / "report.md"
    report_html_path = dir_path / "report.html"

    report_md_path.write_text(md_content, encoding="utf-8")
    report_html_path.write_text(html_content, encoding="utf-8")

    return report_md_path, report_html_path
