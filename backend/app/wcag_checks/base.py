"""
Base class for all WCAG checks.

Each check yields progress dicts via async generator so the API can stream
them live over WebSocket. Yielded shapes:
  { "type": "progress",  "test": TEST_ID, "message": str }
  { "type": "result",    "test": TEST_ID, "data": TestResult.__dict__ }

The `analyzer` is a MolmoWebAnalyzer instance shared across all checks in a
page scan. It provides screenshot utilities and visual QA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator, Optional

if TYPE_CHECKING:
    from app.models.molmo2 import MolmoWebAnalyzer


@dataclass
class TestResult:
    test_id: str
    test_name: str
    result: str              # "pass" | "fail" | "warning" | "error"
    wcag_criteria: list[str]
    severity: str            # "critical" | "major" | "minor"
    failure_reason: str = ""
    recommendation: str = ""
    screenshot_path: Optional[str] = None
    screenshot_b64: Optional[str] = None
    details: dict = field(default_factory=dict)
    molmo_analysis: str = ""         # raw MolmoWeb-8B response for eval dataset
    page_url: str = ""               # set by the crawler after the fact
    timestamp: str = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )


class BaseWCAGTest:
    TEST_ID: str = ""
    TEST_NAME: str = ""
    WCAG_CRITERIA: list[str] = []
    DEFAULT_SEVERITY: str = "major"

    # Visual WCAG question sent to MolmoWeb-8B after programmatic checks.
    # Subclasses override this to get a visual analysis layer on top.
    MOLMO_QUESTION: Optional[str] = None

    # Max seconds to wait for MolmoWeb visual analysis (it runs on GPU).
    MOLMO_TIMEOUT: float = 45.0

    def __init__(
        self,
        analyzer: "MolmoWebAnalyzer",
        run_dir: Path,
        wcag_version: str = "2.2",
    ):
        self.analyzer = analyzer
        self.run_dir = run_dir
        self.wcag_version = wcag_version

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        """
        Override in subclasses. Yield progress and result dicts.
        """
        raise NotImplementedError

    async def _probe_agent_capable(self, page) -> bool:
        """
        Quick capability probe: ask MolmoWeb for one action and check whether
        the output is a parseable action call or trajectory gibberish.
        Returns False if MolmoWeb is in trajectory mode (numbered lists,
        coordinates without context) — callers should skip agent loops.
        """
        if self.analyzer is None:
            return False
        import asyncio
        try:
            screenshot = await self.analyzer.screenshot_to_image(page)
            raw = await asyncio.wait_for(
                self.analyzer.analyze_raw(
                    screenshot,
                    "Task: Check if this page has loaded.\nPrevious actions: none\n"
                    "Choose ONE action. x and y coordinates are 0-100:\n"
                    "  done(\"reason\")\n  mouse_click(x, y)\nAction:",
                    max_new_tokens=30,
                ),
                timeout=20.0,
            )
            # Parseable if it contains a known action keyword
            lower = raw.strip().lower()
            return any(kw in lower for kw in ("done(", "mouse_click(", "key_press(", "mouse_scroll(", "type_text("))
        except Exception:
            return False

    async def _molmo_analyze(self, screenshot, question: str) -> str:
        """
        Run MolmoWeb-8B visual QA with a per-call timeout guard.
        Returns empty string if analyzer unavailable or times out.
        """
        if self.analyzer is None or not question:
            return ""
        import asyncio
        try:
            return await asyncio.wait_for(
                self.analyzer.analyze(screenshot, question),
                timeout=self.MOLMO_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return "[MolmoWeb timed out]"
        except Exception as e:
            return f"[MolmoWeb error: {e}]"

    def _progress(self, message: str) -> dict:
        return {"type": "progress", "test": self.TEST_ID, "message": message}

    def _result(self, result: TestResult) -> dict:
        return {"type": "result", "test": self.TEST_ID, "data": result.__dict__}
