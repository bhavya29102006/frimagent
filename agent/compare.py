"""Before/after test comparison and reporting for autonomous bug fixes."""

import html
from pathlib import Path
from agent.models import FixAttempt


def format_comparison_summary(attempt: FixAttempt) -> str:
    """Format a clear CLI text summary of the fix attempt outcomes."""
    b = attempt.before_counts
    a = attempt.after_counts or {}

    fixed_str = ", ".join(attempt.fixed_tests) if attempt.fixed_tests else "None"
    reg_str = ", ".join(attempt.regressions) if attempt.regressions else "None"

    lines = [
        "=" * 60,
        f"AUTONOMOUS FIX VERIFICATION SUMMARY: [{attempt.attempt_id}]",
        "=" * 60,
        f"Status:      {attempt.status.upper()}",
        f"Before Fix:  Total: {b.get('total', 0)} | Passed: {b.get('passed', 0)} | Failed: {b.get('failed', 0)} | Errors: {b.get('errors', 0)}",
        f"After Fix:   Total: {a.get('total', 0)} | Passed: {a.get('passed', 0)} | Failed: {a.get('failed', 0)} | Errors: {a.get('errors', 0)}",
        f"Fixed Tests: ({len(attempt.fixed_tests)}) {fixed_str}",
        f"Regressions: ({len(attempt.regressions)}) {reg_str}",
        "=" * 60,
    ]
    return "\n".join(lines)


def render_before_after_section_md(attempt: FixAttempt) -> str:
    """Generate GitHub-flavored Markdown section for report.md."""
    b = attempt.before_counts
    a = attempt.after_counts or {}

    b_passed = b.get("passed", 0)
    a_passed = a.get("passed", 0)
    delta_passed = a_passed - b_passed
    delta_passed_str = f"+{delta_passed}" if delta_passed >= 0 else f"{delta_passed}"

    b_failed = b.get("failed", 0)
    a_failed = a.get("failed", 0)
    delta_failed = a_failed - b_failed
    delta_failed_str = f"{delta_failed}" if delta_failed <= 0 else f"+{delta_failed}"

    b_errors = b.get("errors", 0)
    a_errors = a.get("errors", 0)
    delta_errors = a_errors - b_errors

    fixed_str = ", ".join(f"`{t}`" for t in attempt.fixed_tests) if attempt.fixed_tests else "*None*"
    reg_str = ", ".join(f"`{t}`" for t in attempt.regressions) if attempt.regressions else "*None*"

    status_badge = (
        "✅ VALIDATED"
        if attempt.status in ("validated", "applied")
        else f"❌ {attempt.status.upper()}"
    )

    md = [
        "## Before vs After Fix\n",
        f"**Fix Attempt**: `{attempt.attempt_id}` | **Status**: {status_badge}\n",
        "| Metric | Before Fix | After Fix | Delta |",
        "| :--- | :---: | :---: | :---: |",
        f"| **Passed** | {b_passed} | {a_passed} | **{delta_passed_str}** |",
        f"| **Failed** | {b_failed} | {a_failed} | **{delta_failed_str}** |",
        f"| **Errors** | {b_errors} | {a_errors} | {delta_errors} |",
        "",
        f"- **Fixed Tests**: {fixed_str}",
        f"- **Regressions**: {reg_str}",
        f"- **Patch Summary**: {attempt.proposal.summary}",
        "",
    ]
    return "\n".join(md)


def render_before_after_section_html(attempt: FixAttempt) -> str:
    """Generate HTML card for report.html."""
    b = attempt.before_counts
    a = attempt.after_counts or {}

    b_passed = b.get("passed", 0)
    a_passed = a.get("passed", 0)
    delta_passed = a_passed - b_passed
    delta_passed_str = f"+{delta_passed}" if delta_passed >= 0 else f"{delta_passed}"

    b_failed = b.get("failed", 0)
    a_failed = a.get("failed", 0)
    delta_failed = a_failed - b_failed
    delta_failed_str = f"{delta_failed}" if delta_failed <= 0 else f"+{delta_failed}"

    fixed_badges = (
        " ".join(f'<span class="badge badge-pass">{html.escape(t)}</span>' for t in attempt.fixed_tests)
        if attempt.fixed_tests
        else '<span style="color: #94A3B8; font-style: italic;">None</span>'
    )
    reg_badges = (
        " ".join(f'<span class="badge badge-fail">{html.escape(t)}</span>' for t in attempt.regressions)
        if attempt.regressions
        else '<span style="color: #22C55E; font-style: italic;">None (0 regressions)</span>'
    )

    status_badge = (
        '<span class="badge badge-pass">✅ VALIDATED</span>'
        if attempt.status in ("validated", "applied")
        else f'<span class="badge badge-fail">❌ {html.escape(attempt.status.upper())}</span>'
    )

    return f"""
    <div class="card" style="border-top: 3px solid #6366F1;">
        <div class="card-header">
            <h2 class="section-title" style="margin: 0;">Before vs After Fix Comparison</h2>
            <div>{status_badge}</div>
        </div>
        <p style="color: #94A3B8; margin-top: 0;">Attempt ID: <code>{html.escape(attempt.attempt_id)}</code> — {html.escape(attempt.proposal.summary)}</p>
        <table>
            <thead>
                <tr>
                    <th>Metric</th>
                    <th>Before Fix</th>
                    <th>After Fix</th>
                    <th>Delta</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><strong>Passed Tests</strong></td>
                    <td>{b_passed}</td>
                    <td style="color: #22C55E;"><strong>{a_passed}</strong></td>
                    <td style="color: #22C55E;"><strong>{delta_passed_str}</strong></td>
                </tr>
                <tr>
                    <td><strong>Failed Tests</strong></td>
                    <td>{b_failed}</td>
                    <td style="color: #EF4444;"><strong>{a_failed}</strong></td>
                    <td style="color: #22C55E;"><strong>{delta_failed_str}</strong></td>
                </tr>
            </tbody>
        </table>
        <div style="margin-top: 14px;">
            <p><strong>Fixed Tests:</strong> {fixed_badges}</p>
            <p><strong>Regressions:</strong> {reg_badges}</p>
        </div>
    </div>
    """


def update_reports_with_fix(
    run_dir: Path | str,
    attempt: FixAttempt,
) -> tuple[Path, Path]:
    """Append or update Before vs After Fix section in report.md and report.html."""
    r_dir = Path(run_dir)
    report_md_path = r_dir / "report.md"
    report_html_path = r_dir / "report.html"

    md_section = render_before_after_section_md(attempt)
    html_section = render_before_after_section_html(attempt)

    # 1. Update report.md
    if report_md_path.is_file():
        content = report_md_path.read_text(encoding="utf-8")
        if "## Before vs After Fix" in content:
            # Replace existing section
            parts = content.split("## Before vs After Fix")
            tail = parts[1].split("\n## ", 1)
            rest = f"\n## {tail[1]}" if len(tail) > 1 else ""
            content = parts[0] + md_section + rest
        else:
            # Insert before Root Cause Findings or append
            if "## Root-Cause Findings" in content:
                content = content.replace("## Root-Cause Findings", f"{md_section}\n## Root-Cause Findings")
            else:
                content = content + "\n" + md_section
        report_md_path.write_text(content, encoding="utf-8")

    # 2. Update report.html
    if report_html_path.is_file():
        h_content = report_html_path.read_text(encoding="utf-8")
        if "Before vs After Fix Comparison" in h_content:
            # Already inserted, skip duplicate
            pass
        else:
            target_marker = "<!-- Root Cause Findings -->"
            if target_marker in h_content:
                h_content = h_content.replace(target_marker, f"{html_section}\n{target_marker}")
            else:
                h_content = h_content.replace("</div>\n</body>", f"{html_section}\n</div>\n</body>")
            report_html_path.write_text(h_content, encoding="utf-8")

    return report_md_path, report_html_path
