"""
Pydantic schemas for the MolmoAccess Agent API.

All response types are backward-compatible with the existing PointCheck
frontend — the single-page `report` field is preserved; multi-page crawls
add a `pages` array on top.
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, HttpUrl, field_validator


# ── Request ────────────────────────────────────────────────────────────────────

ALL_TESTS = [
    "keyboard_nav",
    "zoom",
    "color_blindness",
    "focus_indicator",
    "form_errors",
    "page_structure",
    "video_motion",
]


class CrawlRequest(BaseModel):
    url: str
    wcag_version: str = "2.2"       # "2.1" or "2.2"
    max_pages: int = 30              # BFS page budget (capped at 30)
    max_depth: int = 3               # BFS depth limit
    tests: list[str] = ALL_TESTS    # subset of ALL_TESTS

    @field_validator("url")
    @classmethod
    def normalize_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            return f"https://{v}"
        return v

    @field_validator("wcag_version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        return v if v in ("2.1", "2.2") else "2.2"

    @field_validator("max_pages")
    @classmethod
    def cap_pages(cls, v: int) -> int:
        return min(max(1, v), 30)

    @field_validator("max_depth")
    @classmethod
    def cap_depth(cls, v: int) -> int:
        # Allow 0 for single-page mode (the /api/run legacy shim passes max_depth=0)
        return min(max(0, v), 5)

    @field_validator("tests")
    @classmethod
    def validate_tests(cls, v: list[str]) -> list[str]:
        unknown = [t for t in v if t not in ALL_TESTS]
        if unknown:
            raise ValueError(f"Unknown test(s): {unknown}. Valid: {ALL_TESTS}")
        return v or ALL_TESTS


class CrawlResponse(BaseModel):
    job_id: str
    message: str


# ── Job state (in-memory) ──────────────────────────────────────────────────────

class CrawlJobState(BaseModel):
    """Mutable run state stored in _jobs dict. Not sent directly to clients."""
    job_id: str
    url: str
    wcag_version: str
    max_pages: int
    max_depth: int
    tests: list[str]
    status: str = "queued"           # queued | running | complete | error
    pages_scanned: int = 0
    pages_discovered: int = 0
    error: Optional[str] = None
    created_at: str = ""
    completed_at: Optional[str] = None
    # Populated progressively
    page_results: list[dict[str, Any]] = []
    report: Optional[dict[str, Any]] = None
    narrative: str = ""


# ── WebSocket event payloads ───────────────────────────────────────────────────
# These mirror the existing PointCheck WS event types so the frontend
# needs no changes for single-page events.

class WSEvent(BaseModel):
    type: str   # status | page_start | test_start | progress | result | page_done | done | error


# ── Report types (frontend-compatible) ────────────────────────────────────────

class TestSummary(BaseModel):
    test_id: str
    test_name: str
    result: str          # pass | fail | warning | error
    severity: str
    failure_reason: str
    wcag_criteria: list[str]
    recommendation: str
    screenshot_path: Optional[str]
    screenshot_b64: Optional[str]
    details: Optional[dict[str, Any]]
    molmo_analysis: Optional[str] = None   # raw MolmoWeb-8B response


class PageReport(BaseModel):
    """Per-page report. Same structure as existing single-page report."""
    page_url: str
    depth: int
    overall_status: str
    compliance_percentage: float
    summary: dict[str, int]
    test_summaries: list[TestSummary]
    critical_failures: list[dict[str, Any]]
    all_failures: list[dict[str, Any]]
    raw_results: list[dict[str, Any]]
    screenshot_path: Optional[str] = None


class SiteReport(BaseModel):
    """
    Full site report returned in the `done` event and GET /api/crawl/{job_id}.
    Backward-compatible: top-level fields mirror the single-page report format;
    `pages` is additive.
    """
    job_id: str
    url: str
    wcag_version: str
    generated_at: str
    narrative: str
    overall_status: str
    compliance_percentage: float
    pages_scanned: int
    summary: dict[str, int]
    top_criteria_failures: list[dict[str, Any]]
    test_summaries: list[dict[str, Any]]  # aggregated across all pages
    critical_failures: list[dict[str, Any]]
    all_failures: list[dict[str, Any]]
    raw_results: list[dict[str, Any]]
    pages: list[dict[str, Any]]          # per-page breakdowns (additive)
