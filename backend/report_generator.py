"""
Generates compliance summary reports from raw test results.
Returns a dict that can be serialized to JSON, exported to CSV, or rendered as HTML.
"""

from datetime import datetime

WCAG_CRITERIA_LABELS = {
    "1.1.1": "Non-text Content",
    "1.3.1": "Info and Relationships",
    "1.4.1": "Use of Color",
    "1.4.3": "Contrast (Minimum)",
    "1.4.4": "Resize Text",
    "1.4.10": "Reflow",
    "2.1.1": "Keyboard",
    "2.1.2": "No Keyboard Trap",
    "2.4.3": "Focus Order",
    "2.4.7": "Focus Visible",
    "3.3.1": "Error Identification",
    "3.3.2": "Labels or Instructions",
    "3.3.3": "Error Suggestion",
    "3.3.4": "Error Prevention",
}

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "warning": 3}

TEST_LABELS = {
    "keyboard_nav": "Keyboard-Only Navigation",
    "zoom": "200% Zoom / Reflow",
    "color_blindness": "Color Blindness Simulation",
    "focus_indicator": "Focus Visibility",
    "form_errors": "Form Error Handling",
}


def generate_report(run: dict) -> dict:
    results = run.get("results", [])
    tests_run = run.get("tests", [])
    url = run.get("url", "")

    passed = [r for r in results if r.get("result") == "pass"]
    failed = [r for r in results if r.get("result") == "fail"]
    warnings = [r for r in results if r.get("result") == "warning"]
    errors = [r for r in results if r.get("result") == "error"]

    total = len(results)
    pass_count = len(passed)
    compliance_pct = round((pass_count / total * 100) if total > 0 else 0, 1)

    # Aggregate failing WCAG criteria
    criteria_failures: dict[str, int] = {}
    for r in failed:
        for crit in r.get("wcag_criteria", []):
            criteria_failures[crit] = criteria_failures.get(crit, 0) + 1

    top_criteria = sorted(criteria_failures.items(), key=lambda x: -x[1])

    # Sort failures by severity
    sorted_failures = sorted(
        failed, key=lambda r: SEVERITY_ORDER.get(r.get("severity", "minor"), 3)
    )

    # Per-test summary
    test_summaries = []
    for test_id in tests_run:
        result = next((r for r in results if r.get("test_id") == test_id), None)
        test_summaries.append({
            "test_id": test_id,
            "test_name": TEST_LABELS.get(test_id, test_id),
            "result": result.get("result", "not_run") if result else "not_run",
            "severity": result.get("severity", "") if result else "",
            "failure_reason": result.get("failure_reason", "") if result else "",
            "wcag_criteria": result.get("wcag_criteria", []) if result else [],
            "recommendation": result.get("recommendation", "") if result else "",
            "screenshot_path": result.get("screenshot_path") if result else None,
            "screenshot_b64": result.get("screenshot_b64") if result else None,
            "details": result.get("details") if result else None,
        })

    overall_status = "compliant" if not failed else (
        "critical_issues" if any(r.get("severity") == "critical" for r in failed) else "issues_found"
    )

    return {
        "run_id": run.get("run_id"),
        "narrative": run.get("narrative", ""),
        "url": url,
        "generated_at": datetime.utcnow().isoformat(),
        "overall_status": overall_status,
        "compliance_percentage": compliance_pct,
        "summary": {
            "total_tests": total,
            "passed": pass_count,
            "failed": len(failed),
            "warnings": len(warnings),
            "errors": len(errors),
        },
        "top_criteria_failures": [
            {
                "criterion": crit,
                "label": WCAG_CRITERIA_LABELS.get(crit, crit),
                "failure_count": count,
            }
            for crit, count in top_criteria[:5]
        ],
        "test_summaries": test_summaries,
        "critical_failures": [
            r for r in sorted_failures if r.get("severity") == "critical"
        ],
        "all_failures": sorted_failures,
        "raw_results": results,
    }


def to_csv(report: dict) -> str:
    """Export test summaries as CSV string."""
    lines = ["Test,Result,Severity,WCAG Criteria,Failure Reason,Recommendation"]
    for ts in report.get("test_summaries", []):
        criteria = "|".join(ts.get("wcag_criteria", []))
        reason = ts.get("failure_reason", "").replace('"', "'")
        rec = ts.get("recommendation", "").replace('"', "'")
        lines.append(
            f'"{ts["test_name"]}","{ts["result"]}","{ts["severity"]}",'
            f'"{criteria}","{reason}","{rec}"'
        )
    return "\n".join(lines)
