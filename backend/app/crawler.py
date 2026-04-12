"""
MolmoAccess BFS Site Crawler.

Architecture:
  - Playwright drives the browser (navigation, DOM inspection, screenshots).
  - MolmoWebAnalyzer (MolmoWeb-8B) runs visual WCAG analysis on each page.
  - BFS queue respects robots.txt, max_pages=30, max_depth=3.
  - Per-page flow:
      1. Navigate to URL
      2. Run 7 programmatic WCAG checks (each with per-check Molmo QA)
      3. Take full-page screenshot
      4. Run holistic vision analysis (analyze_screenshot_with_molmo2)
      5. Capture video frames + run video-specific analysis
      6. Merge all results → page report
      7. Log everything to EvalLogger JSONL

MolmoWeb integration note:
  MolmoWeb is a VLM action policy, not a traditional browser library.
  We do NOT load MolmoWeb-8B as a navigator — that would be expensive and
  non-deterministic for BFS. Instead, MolmoWebAnalyzer (same model) is used
  purely for visual WCAG analysis (screenshot QA + element pointing).
  Playwright handles all navigation reliably.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from app.eval_logger import EvalLogger
from app.models.molmo2 import MolmoWebAnalyzer
from app.report_generator import build_page_report
from app.vision_analysis import (
    analyze_screenshot_with_molmo2,
    analyze_video_frame,
    capture_video_frames,
    merge_vision_into_results,
)
from app.wcag_checks import (
    KeyboardNavTest,
    ZoomTest,
    ColorBlindnessTest,
    FocusIndicatorTest,
    FormErrorTest,
    PageStructureTest,
    VideoMotionTest,
)
from app.wcag_checks.base import BaseWCAGTest

# Tests that are safe to run on every page in a crawl
# (zoom resets CDP scale; form_errors may navigate away — both reset-safe)
TEST_MAP: dict[str, type[BaseWCAGTest]] = {
    "keyboard_nav":    KeyboardNavTest,
    "zoom":            ZoomTest,
    "color_blindness": ColorBlindnessTest,
    "focus_indicator": FocusIndicatorTest,
    "form_errors":     FormErrorTest,
    "page_structure":  PageStructureTest,
    "video_motion":    VideoMotionTest,
}

# Delay between page requests (ms) to avoid hammering servers
_INTER_PAGE_DELAY_MS = 800


# ── Cookie consent dismissal ──────────────────────────────────────────────────

async def _dismiss_cookie_consent(page: Page) -> None:
    """
    Try common cookie/GDPR consent patterns and click Accept if found.
    Tries each selector with a short timeout — silently skips if not present.
    Called after every page.goto() so MolmoWeb sees the real page content.
    """
    selectors = [
        # Text-based buttons (most reliable)
        "button:has-text('Accept all')",
        "button:has-text('Accept All')",
        "button:has-text('Accept cookies')",
        "button:has-text('Accept Cookies')",
        "button:has-text('Accept')",
        "button:has-text('Agree')",
        "button:has-text('OK')",
        "button:has-text('Got it')",
        "button:has-text('I agree')",
        "button:has-text('Allow all')",
        "button:has-text('Allow All')",
        "button:has-text('Continue')",
        # ID/class pattern matches
        "#onetrust-accept-btn-handler",
        "#accept-cookies",
        "#cookie-accept",
        "[id*='cookie'] button[class*='accept']",
        "[id*='cookie'] button[class*='agree']",
        "[id*='consent'] button[class*='accept']",
        "[id*='consent'] button[class*='agree']",
        "[class*='cookie-banner'] button",
        "[class*='cookie-notice'] button",
        "[class*='gdpr'] button[class*='accept']",
        # Aria-label patterns
        "[aria-label*='Accept']",
        "[aria-label*='accept cookies']",
        "[aria-label*='cookie']",
    ]
    for sel in selectors:
        try:
            await page.click(sel, timeout=800)
            await asyncio.sleep(0.4)
            return  # stop after first successful dismiss
        except Exception:
            continue

# Extensions to skip — not meaningful HTML pages
_SKIP_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".mp4", ".mp3", ".wav", ".zip", ".tar", ".gz", ".exe",
    ".css", ".js", ".json", ".xml", ".ico", ".woff", ".woff2",
    ".ttf", ".eot",
}


# ── Robots.txt cache ──────────────────────────────────────────────────────────

def _build_robots_parser(base_url: str) -> Optional[RobotFileParser]:
    try:
        parsed = urlparse(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp
    except Exception:
        return None


def _robots_allows(rp: Optional[RobotFileParser], url: str) -> bool:
    if rp is None:
        return True
    try:
        return rp.can_fetch("*", url)
    except Exception:
        return True


# ── URL normalization + link extraction ───────────────────────────────────────

def _normalize_url(url: str) -> str:
    """Remove fragment, normalize trailing slash for dedup."""
    p = urlparse(url)
    # Drop fragment, keep path/query
    normalized = p._replace(fragment="").geturl()
    # Remove trailing ? with no params
    if normalized.endswith("?"):
        normalized = normalized[:-1]
    return normalized


def _same_origin(url: str, base: str) -> bool:
    pu, pb = urlparse(url), urlparse(base)
    return pu.netloc == pb.netloc


def _skip_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    _, ext = path.rsplit(".", 1) if "." in path.split("/")[-1] else ("", "")
    return f".{ext}" in _SKIP_EXTENSIONS


async def _extract_links(page: Page, base_url: str) -> list[str]:
    """Return all same-origin, non-skippable href links found on the page."""
    hrefs: list[str] = await page.evaluate("""() => {
        return Array.from(document.querySelectorAll('a[href]'))
            .map(a => a.getAttribute('href'))
            .filter(h => h && !h.startsWith('javascript:') && !h.startsWith('mailto:')
                      && !h.startsWith('tel:') && !h.startsWith('#'));
    }""")
    links = []
    for href in hrefs:
        absolute = urljoin(base_url, href)
        normalized = _normalize_url(absolute)
        if _same_origin(normalized, base_url) and not _skip_url(normalized):
            links.append(normalized)
    return list(dict.fromkeys(links))  # deduplicate while preserving order


# ── Per-page WCAG scan ────────────────────────────────────────────────────────

async def _scan_page(
    page: Page,
    page_url: str,
    depth: int,
    tests_to_run: list[str],
    analyzer: MolmoWebAnalyzer,
    run_dir: Path,
    wcag_version: str,
    eval_logger: Optional[EvalLogger],
) -> AsyncGenerator[dict, None]:
    """
    Navigate to `page_url`, run all requested WCAG checks, yield events.
    Returns (via StopAsyncIteration) the list of TestResult dicts.
    """
    page_slug = re.sub(r'[^\w]', '_', page_url[8:])[:40]  # strip https://
    page_run_dir = run_dir / page_slug
    page_run_dir.mkdir(exist_ok=True)

    yield {"type": "page_start", "url": page_url, "depth": depth}

    try:
        await page.goto(page_url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(1.5)  # let JS-heavy SPAs settle
        await _dismiss_cookie_consent(page)
    except Exception as e:
        yield {"type": "page_error", "url": page_url, "error": str(e)}
        return

    results: list[dict] = []

    for i, test_id in enumerate(tests_to_run):
        test_cls = TEST_MAP[test_id]
        test = test_cls(
            analyzer=analyzer,
            run_dir=page_run_dir,
            wcag_version=wcag_version,
        )

        yield {
            "type": "test_start",
            "url": page_url,
            "test": test_id,
            "test_name": test.TEST_NAME,
            "index": i,
            "total": len(tests_to_run),
        }

        # Reset page state before each test
        try:
            await page.goto(page_url, wait_until="domcontentloaded", timeout=20_000)
            await asyncio.sleep(1.0)
            await _dismiss_cookie_consent(page)
        except Exception:
            pass  # best effort; some pages redirect

        async for event in test.run(page, task="Evaluate web accessibility"):
            # Stamp page_url into result events
            if event["type"] == "result":
                event["data"]["page_url"] = page_url
                results.append(dict(event["data"]))
                # Log to eval dataset
                if eval_logger:
                    eval_logger.log_from_test_result(
                        page_url=page_url,
                        page_depth=depth,
                        check_id=test_id,
                        check_name=test.TEST_NAME,
                        result_dict=event["data"],
                    )
            yield event

        yield {"type": "test_complete", "url": page_url, "test": test_id}

    # ── Step 1b: Mobile-viewport keyboard nav (hamburger menu discovery) ──
    # Re-run keyboard_nav at 390×844 (iPhone 14) so the agent can find and
    # test hamburger menus and mobile nav toggles that are hidden at 1280px.
    # Only runs if keyboard_nav was requested and the desktop run didn't find
    # a keyboard trap (trap = stop early, no point retesting mobile).
    if "keyboard_nav" in tests_to_run:
        desktop_kb_result = next(
            (r for r in results if r.get("test_id") == "keyboard_nav"), None
        )
        desktop_was_trap = (
            desktop_kb_result is not None
            and "2.1.2" in desktop_kb_result.get("wcag_criteria", [])
            and desktop_kb_result.get("result") == "fail"
        )
        if not desktop_was_trap:
            yield {
                "type": "progress",
                "test": "keyboard_nav_mobile",
                "message": "[MOBILE 390px] Re-running keyboard nav at mobile viewport to discover hamburger menus...",
            }
            try:
                mobile_context = await page.context.browser.new_context(
                    viewport={"width": 390, "height": 844},
                    user_agent=(
                        "MolmoAccessBot/1.0 "
                        "(+https://github.com/BrendanWorks/molmoaccess; "
                        "accessibility-testing-bot)"
                    ),
                )
                mobile_page = await mobile_context.new_page()
                await mobile_page.goto(page_url, wait_until="domcontentloaded", timeout=30_000)
                await asyncio.sleep(1.5)
                await _dismiss_cookie_consent(mobile_page)

                from app.wcag_checks.keyboard_nav import KeyboardNavTest
                mobile_kb_test = KeyboardNavTest(
                    analyzer=analyzer,
                    run_dir=page_run_dir,
                    wcag_version=wcag_version,
                )
                async for event in mobile_kb_test.run(mobile_page, task="Evaluate mobile keyboard accessibility"):
                    if event["type"] == "progress":
                        # Prefix mobile events so they're distinguishable in the stream
                        event["message"] = "[MOBILE] " + event.get("message", "")
                    elif event["type"] == "result":
                        event["data"]["page_url"] = page_url
                        event["data"]["test_name"] = "Keyboard Nav (Mobile 390px)"
                        # Only surface as a new result if mobile found something desktop missed
                        desktop_passed = desktop_kb_result and desktop_kb_result.get("result") == "pass"
                        if event["data"].get("result") != "pass" or desktop_passed:
                            event["data"]["test_id"] = "keyboard_nav_mobile"
                            results.append(dict(event["data"]))
                    yield event

                await mobile_page.close()
                await mobile_context.close()
            except Exception as e:
                yield {
                    "type": "progress",
                    "test": "keyboard_nav_mobile",
                    "message": f"[MOBILE] viewport test error (non-fatal): {e}",
                }

    # ── Step 2: Holistic vision analysis ─────────────────────────────────
    # One full-page screenshot → MolmoWeb-8B answers all 7 WCAG categories.
    # Supplements (never overrides) the per-check programmatic results above.
    yield {"type": "progress", "test": "vision_holistic",
           "message": "Running holistic MolmoWeb-8B vision analysis..."}

    vision_issues: list[dict] = []
    video_findings: list[dict] = []

    try:
        # Navigate back cleanly for the holistic screenshot
        await page.goto(page_url, wait_until="domcontentloaded", timeout=20_000)
        await asyncio.sleep(1.0)
        await _dismiss_cookie_consent(page)

        # Build context from what programmatic checks already found
        existing_failure_ids = {
            r["test_id"] for r in results if r.get("result") == "fail"
        }
        page_context = {
            "existing_failure_test_ids": existing_failure_ids,
            "hints": [],
        }

        page_screenshot_bytes = await page.screenshot(full_page=False)

        vision_issues = await analyze_screenshot_with_molmo2(
            image_bytes=page_screenshot_bytes,
            wcag_version=wcag_version,
            analyzer=analyzer,
            page_url=page_url,
            page_context=page_context,
        )

        if vision_issues:
            yield {
                "type": "progress",
                "test": "vision_holistic",
                "message": f"Vision analysis found {len(vision_issues)} visual issue(s).",
            }
        else:
            yield {
                "type": "progress",
                "test": "vision_holistic",
                "message": "Vision analysis: no additional visual issues detected.",
            }

        # ── Step 3: Video frame analysis ──────────────────────────────────
        video_frames = await capture_video_frames(page, page_run_dir)
        if video_frames:
            yield {
                "type": "progress",
                "test": "vision_holistic",
                "message": f"Analyzing {len(video_frames)} video frame(s) for captions and controls...",
            }
            for frame_bytes, video_info in video_frames:
                findings = await analyze_video_frame(
                    frame_bytes=frame_bytes,
                    analyzer=analyzer,
                    page_url=page_url,
                )
                findings["video_info"] = video_info

                # Propagate flicker_risk from multi-frame motion analysis into issues
                if video_info.get("flicker_risk"):
                    findings.setdefault("issues", []).append({
                        "wcag_criterion": "2.3.1",
                        "severity": "critical",
                        "description": (
                            f"Rapid pixel change detected across consecutive frames "
                            f"(motion_score={video_info.get('motion_score', '?')}). "
                            "Content may flash >3 times/second — photosensitive seizure risk."
                        ),
                    })

                video_findings.append(findings)

                # Summarize pointing results for eval log
                pointing_detail = ""
                if findings.get("caption_button_xy"):
                    pointing_detail += f"caption_btn={findings['caption_button_xy']}; "
                if findings.get("playpause_button_xy"):
                    pointing_detail += f"playpause_btn={findings['playpause_button_xy']}"

                # Log video frame analysis to eval dataset
                if eval_logger:
                    eval_logger.log(
                        page_url=page_url,
                        page_depth=depth,
                        check_id="video_motion",
                        check_name="Video Frame Analysis",
                        wcag_criteria=["1.2.2", "2.2.2", "2.3.1"],
                        result="warning" if findings.get("issues") else "pass",
                        severity="critical" if video_info.get("flicker_risk") else (
                            "major" if findings.get("issues") else "minor"
                        ),
                        failure_reason="; ".join(
                            i.get("description", "") for i in findings.get("issues", [])[:2]
                        ),
                        molmo_prompt=f"[video frame QA + pointing; {pointing_detail}]",
                        molmo_response=findings.get("raw_response", ""),
                        screenshot_path=video_info.get("frame_path"),
                    )

    except Exception as e:
        yield {
            "type": "progress",
            "test": "vision_holistic",
            "message": f"Vision analysis error (non-fatal): {e}",
        }

    # Log vision issues to eval dataset
    for vi in vision_issues:
        if eval_logger:
            eval_logger.log_from_test_result(
                page_url=page_url,
                page_depth=depth,
                check_id=f"vision_{vi.get('test_id', 'unknown')}",
                check_name=vi.get("test_name", ""),
                result_dict=vi,
            )

    # ── Step 4: Merge all results ─────────────────────────────────────────
    merged_results = merge_vision_into_results(
        programmatic_results=results,
        vision_issues=vision_issues,
        video_findings=video_findings,
    )

    page_report = build_page_report(
        page_url=page_url,
        depth=depth,
        results=merged_results,
        tests_run=tests_to_run,
    )
    yield {"type": "page_done", "url": page_url, "page_report": page_report}


# ── BFS crawler ───────────────────────────────────────────────────────────────

class SiteCrawler:
    """
    BFS crawler that visits up to `max_pages` pages up to `max_depth` deep,
    running all requested WCAG checks on each page.

    Usage:
        async for event in crawler.crawl():
            await ws.send_json(event)
    """

    def __init__(
        self,
        start_url: str,
        analyzer: MolmoWebAnalyzer,
        screenshots_dir: Path,
        wcag_version: str = "2.2",
        max_pages: int = 30,
        max_depth: int = 3,
        tests: list[str] | None = None,
        eval_logger: Optional[EvalLogger] = None,
    ):
        self.start_url    = _normalize_url(start_url)
        self.analyzer     = analyzer
        self.screenshots_dir = screenshots_dir
        self.wcag_version = wcag_version
        self.max_pages    = min(max_pages, 30)
        self.max_depth    = min(max_depth, 5)
        self.tests        = tests or list(TEST_MAP.keys())
        self.eval_logger  = eval_logger
        self._page_reports: list[dict] = []

    async def crawl(self) -> AsyncGenerator[dict, None]:
        """
        Main entry point. Yields WS-compatible event dicts.
        After all pages, yields a final `crawl_done` event with all page reports.
        """
        robots = await asyncio.get_event_loop().run_in_executor(
            None, _build_robots_parser, self.start_url
        )

        visited: set[str] = set()
        # Queue items: (url, depth)
        queue: deque[tuple[str, int]] = deque([(self.start_url, 0)])

        yield {
            "type": "status",
            "message": f"Starting BFS crawl from {self.start_url} "
                       f"(max {self.max_pages} pages, depth {self.max_depth})",
        }

        async with async_playwright() as pw:
            browser: Browser = await pw.chromium.launch(headless=True)
            context: BrowserContext = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "MolmoAccessBot/1.0 "
                    "(+https://github.com/BrendanWorks/molmoaccess; "
                    "accessibility-testing-bot)"
                ),
            )

            page: Page = await context.new_page()

            # Throttle network to be a polite crawler
            await context.route(
                re.compile(r"\.(woff2?|ttf|eot|mp4|mp3|wav)$"),
                lambda route, _: route.abort(),
            )

            while queue and len(visited) < self.max_pages:
                url, depth = queue.popleft()

                if url in visited:
                    continue
                if not _robots_allows(robots, url):
                    yield {"type": "status", "message": f"Skipping {url} (robots.txt)"}
                    continue

                visited.add(url)
                pages_done = len(visited)

                yield {
                    "type": "status",
                    "message": f"[{pages_done}/{self.max_pages}] Scanning {url} (depth {depth})",
                }

                # Run all WCAG checks on this page, stream events
                page_report: dict | None = None
                async for event in _scan_page(
                    page=page,
                    page_url=url,
                    depth=depth,
                    tests_to_run=self.tests,
                    analyzer=self.analyzer,
                    run_dir=self.screenshots_dir,
                    wcag_version=self.wcag_version,
                    eval_logger=self.eval_logger,
                ):
                    if event["type"] == "page_done":
                        page_report = event["page_report"]
                        self._page_reports.append(page_report)
                    yield event

                # Discover links only if we haven't hit depth limit
                if depth < self.max_depth and len(visited) < self.max_pages:
                    try:
                        # Navigate back to the page cleanly for link extraction
                        await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                        await asyncio.sleep(0.5)
                        await _dismiss_cookie_consent(page)
                        links = await _extract_links(page, self.start_url)
                        new_links = [
                            lnk for lnk in links
                            if lnk not in visited
                            and lnk not in {u for u, _ in queue}
                        ]
                        for lnk in new_links:
                            if len(visited) + len(queue) < self.max_pages * 2:
                                queue.append((lnk, depth + 1))
                        yield {
                            "type": "status",
                            "message": (
                                f"Discovered {len(new_links)} new link(s) from {url}. "
                                f"Queue: {len(queue)} | Visited: {len(visited)}"
                            ),
                        }
                    except Exception as e:
                        yield {"type": "status", "message": f"Link extraction failed for {url}: {e}"}

                # Polite delay between pages
                await asyncio.sleep(_INTER_PAGE_DELAY_MS / 1000)

            await browser.close()

        yield {
            "type": "crawl_done",
            "pages_scanned": len(self._page_reports),
            "page_reports": self._page_reports,
        }

    @property
    def page_reports(self) -> list[dict]:
        return self._page_reports
