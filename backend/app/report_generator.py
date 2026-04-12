"""
Report generator — multi-page aware, backward-compatible with PointCheck v1.

Single-page scan:  returns the same structure as the original PointCheck report.
Multi-page crawl:  same top-level keys PLUS a `pages` list with per-page reports.

The frontend reads `test_summaries`, `compliance_percentage`, `overall_status`,
`critical_failures`, `narrative`, and `raw_results` — all preserved.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

WCAG_CRITERIA_LABELS: dict[str, str] = {
    "1.1.1": "Non-text Content",
    "1.2.1": "Audio-only and Video-only",
    "1.2.2": "Captions (Prerecorded)",
    "1.2.3": "Audio Description (Prerecorded)",
    "1.3.1": "Info and Relationships",
    "1.4.1": "Use of Color",
    "1.4.3": "Contrast (Minimum)",
    "1.4.4": "Resize Text",
    "1.4.10": "Reflow",
    "2.1.1": "Keyboard",
    "2.1.2": "No Keyboard Trap",
    "2.2.2": "Pause, Stop, Hide",
    "2.3.1": "Three Flashes",
    "2.4.1": "Bypass Blocks",
    "2.4.2": "Page Titled",
    "2.4.3": "Focus Order",
    "2.4.4": "Link Purpose",
    "2.4.7": "Focus Visible",
    "2.5.8": "Target Size (Minimum)",
    "3.1.1": "Language of Page",
    "3.3.1": "Error Identification",
    "3.3.2": "Labels or Instructions",
    "3.3.3": "Error Suggestion",
    "3.3.4": "Error Prevention",
    "4.1.1": "Parsing",
    "4.1.2": "Name, Role, Value",
}

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "warning": 3}

TEST_LABELS: dict[str, str] = {
    "keyboard_nav":    "Keyboard-Only Navigation",
    "zoom":            "Resize Text & Reflow",
    "color_blindness": "Color-Blindness & Contrast",
    "focus_indicator": "Focus Visibility",
    "form_errors":     "Form Error Handling",
    "page_structure":  "Page Structure & Semantics",
    "video_motion":    "Video, Audio & Motion",
}


def _overall_status(results: list[dict]) -> str:
    failed = [r for r in results if r.get("result") == "fail"]
    if not failed:
        return "compliant"
    if any(r.get("severity") == "critical" for r in failed):
        return "critical_issues"
    return "issues_found"


def _compliance_pct(results: list[dict]) -> float:
    total = len(results)
    if not total:
        return 0.0
    passed   = sum(1 for r in results if r.get("result") == "pass")
    warnings = sum(1 for r in results if r.get("result") == "warning")
    return round((passed + warnings) / total * 100, 1)


def _top_criteria(results: list[dict], n: int = 5) -> list[dict]:
    counts: dict[str, int] = {}
    for r in results:
        if r.get("result") == "fail":
            for crit in r.get("wcag_criteria", []):
                counts[crit] = counts.get(crit, 0) + 1
    return [
        {
            "criterion": crit,
            "label": WCAG_CRITERIA_LABELS.get(crit, crit),
            "failure_count": count,
        }
        for crit, count in sorted(counts.items(), key=lambda x: -x[1])[:n]
    ]


def build_page_report(
    page_url: str,
    depth: int,
    results: list[dict],
    tests_run: list[str],
    screenshot_path: str | None = None,
) -> dict[str, Any]:
    """
    Build a single-page sub-report. Mirrors the existing PointCheck report
    shape so the frontend's existing rendering code works unchanged.

    Summary counts are derived from test_summaries (one entry per test in
    tests_run) so the count boxes always match the displayed test cards.
    raw_results retains the full merged result list for detailed analysis.
    """
    # Build test_summaries first — one entry per test_id in tests_run,
    # picking the programmatic result (results are ordered programmatic-first).
    test_summaries = []
    for test_id in tests_run:
        r = next((x for x in results if x.get("test_id") == test_id), None)
        test_summaries.append({
            "test_id":        test_id,
            "test_name":      TEST_LABELS.get(test_id, test_id),
            "result":         r.get("result", "not_run") if r else "not_run",
            "severity":       r.get("severity", "") if r else "",
            "failure_reason": r.get("failure_reason", "") if r else "",
            "wcag_criteria":  r.get("wcag_criteria", []) if r else [],
            "recommendation": r.get("recommendation", "") if r else "",
            "screenshot_path": r.get("screenshot_path") if r else None,
            "screenshot_b64":  r.get("screenshot_b64") if r else None,
            "details":         r.get("details") if r else None,
            "molmo_analysis":  r.get("molmo_analysis", "") if r else "",
        })

    # Compute summary counts from test_summaries so they match the cards shown
    # in the UI and PDF.  raw_results keeps the full merged list for detailed
    # failure info and the top-criteria chart.
    ts_passed   = sum(1 for ts in test_summaries if ts["result"] == "pass")
    ts_failed   = sum(1 for ts in test_summaries if ts["result"] == "fail")
    ts_warnings = sum(1 for ts in test_summaries if ts["result"] == "warning")
    ts_errors   = sum(1 for ts in test_summaries if ts["result"] == "error")
    ts_total    = len(test_summaries)

    ts_fail_entries = [ts for ts in test_summaries if ts["result"] == "fail"]
    if not ts_fail_entries:
        overall = "compliant"
    elif any(ts.get("severity") == "critical" for ts in ts_fail_entries):
        overall = "critical_issues"
    else:
        overall = "issues_found"

    compliance = round((ts_passed + ts_warnings) / ts_total * 100, 1) if ts_total else 0.0

    # Keep full raw results for sorted_failures / top_criteria (need severity detail)
    all_raw_failures = sorted(
        [r for r in results if r.get("result") == "fail"],
        key=lambda r: SEVERITY_ORDER.get(r.get("severity", "minor"), 3),
    )

    return {
        "page_url":            page_url,
        "depth":               depth,
        "overall_status":      overall,
        "compliance_percentage": compliance,
        "summary": {
            "total_tests": ts_total,
            "passed":    ts_passed,
            "failed":    ts_failed,
            "warnings":  ts_warnings,
            "errors":    ts_errors,
        },
        "top_criteria_failures": _top_criteria(results),
        "test_summaries":   test_summaries,
        "critical_failures": [r for r in all_raw_failures if r.get("severity") == "critical"],
        "all_failures":     all_raw_failures,
        "raw_results":      results,
        "screenshot_path":  screenshot_path,
    }


def build_site_report(
    job_id: str,
    site_url: str,
    wcag_version: str,
    narrative: str,
    page_reports: list[dict[str, Any]],
    tests_run: list[str],
) -> dict[str, Any]:
    """
    Aggregate per-page reports into a site-wide report.

    Top-level structure is backward-compatible with PointCheck v1 so the
    existing frontend renders correctly for single-page scans. Multi-page
    data is additive in the `pages` key.
    """
    # Flatten all results across pages
    all_results: list[dict] = []
    for pr in page_reports:
        for r in pr.get("raw_results", []):
            r_copy = dict(r)
            r_copy["page_url"] = pr["page_url"]
            all_results.append(r_copy)

    # Aggregate test summaries: worst result per test_id across all pages
    agg_by_test: dict[str, list[dict]] = {}
    for pr in page_reports:
        for ts in pr.get("test_summaries", []):
            tid = ts["test_id"]
            agg_by_test.setdefault(tid, []).append(ts)

    agg_summaries = []
    for test_id in tests_run:
        entries = agg_by_test.get(test_id, [])
        if not entries:
            agg_summaries.append({
                "test_id": test_id,
                "test_name": TEST_LABELS.get(test_id, test_id),
                "result": "not_run", "severity": "",
                "failure_reason": "", "wcag_criteria": [],
                "recommendation": "", "screenshot_path": None,
                "screenshot_b64": None, "details": None,
                "pages_failed": 0, "pages_total": len(page_reports),
            })
            continue

        # Result priority: fail > warning > error > pass
        priority = {"fail": 0, "warning": 1, "error": 2, "pass": 3, "not_run": 4}
        worst = min(entries, key=lambda e: priority.get(e.get("result", "not_run"), 5))
        pages_failed = sum(1 for e in entries if e.get("result") == "fail")

        agg_summaries.append({
            **worst,
            "pages_failed": pages_failed,
            "pages_total":  len(page_reports),
        })

    # Compute summary counts from agg_summaries (one entry per test_id) so
    # the count boxes shown in the UI/PDF always match the test cards.
    # all_results is still used for top_criteria_failures and all_failures
    # which need the full per-page detail.
    agg_passed   = sum(1 for ts in agg_summaries if ts.get("result") == "pass")
    agg_failed   = sum(1 for ts in agg_summaries if ts.get("result") == "fail")
    agg_warnings = sum(1 for ts in agg_summaries if ts.get("result") == "warning")
    agg_errors   = sum(1 for ts in agg_summaries if ts.get("result") == "error")
    agg_total    = len(agg_summaries)

    agg_fail_entries = [ts for ts in agg_summaries if ts.get("result") == "fail"]
    if not agg_fail_entries:
        overall = "compliant"
    elif any(ts.get("severity") == "critical" for ts in agg_fail_entries):
        overall = "critical_issues"
    else:
        overall = "issues_found"

    compliance = round((agg_passed + agg_warnings) / agg_total * 100, 1) if agg_total else 0.0

    sorted_failures = sorted(
        [r for r in all_results if r.get("result") == "fail"],
        key=lambda r: SEVERITY_ORDER.get(r.get("severity", "minor"), 3),
    )

    return {
        # ── Backward-compatible single-page fields ─────────────────────────
        "job_id":              job_id,
        "url":                 site_url,
        "wcag_version":        wcag_version,
        "generated_at":        datetime.utcnow().isoformat(),
        "narrative":           narrative,
        "overall_status":      overall,
        "compliance_percentage": compliance,
        "pages_scanned":       len(page_reports),
        "summary": {
            "total_tests": agg_total,
            "passed":    agg_passed,
            "failed":    agg_failed,
            "warnings":  agg_warnings,
            "errors":    agg_errors,
        },
        "top_criteria_failures": _top_criteria(all_results),
        "test_summaries":   agg_summaries,
        "critical_failures": [r for r in sorted_failures if r.get("severity") == "critical"],
        "all_failures":     sorted_failures,
        "raw_results":      all_results,
        # ── Additive multi-page field ──────────────────────────────────────
        "pages": page_reports,
    }


def strip_b64(obj: Any) -> Any:
    """
    Recursively remove screenshot_b64 keys from a report dict before
    sending over WebSocket — screenshots can push frames past the 1MB limit.
    Individual `result` events during the scan still include b64.
    """
    if isinstance(obj, dict):
        return {k: strip_b64(v) for k, v in obj.items() if k != "screenshot_b64"}
    if isinstance(obj, list):
        return [strip_b64(i) for i in obj]
    return obj
