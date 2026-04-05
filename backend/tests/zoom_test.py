"""
WCAG 2.1 200% Zoom Test
Maps to: 1.4.4 (Resize Text), 1.4.10 (Reflow)

Applies 200% zoom via browser scale factor, takes screenshot,
asks MolmoWeb to assess readability and layout integrity.
"""

import asyncio
from typing import AsyncGenerator

from tests.base_test import BaseWCAGTest, TestResult

PROMPT_TEMPLATE = """Look at this screenshot of a website at 200% browser zoom.

Answer these questions:
1. Is all text readable without being cut off?
2. Does the page require horizontal scrolling?
3. Are any buttons, links, or inputs overlapping or cut off?

Then give your answer as JSON with these fields:
- "text_readable": true or false
- "no_horizontal_scroll": true or false
- "controls_intact": true or false
- "result": "pass" if everything looks good, "fail" if there are problems
- "failure_reason": describe any problems you see, or "" if none
- "wcag_criteria": ["1.4.4", "1.4.10"]
- "severity": "major" if content is broken, "minor" if cosmetic
- "recommendation": suggest a fix, or "" if none needed"""


class ZoomTest(BaseWCAGTest):
    TEST_ID = "zoom"
    TEST_NAME = "200% Zoom Test"
    WCAG_CRITERIA = ["1.4.4", "1.4.10"]
    DEFAULT_SEVERITY = "major"

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        yield self._progress("Capturing baseline screenshot...")
        baseline = await self.agent.screenshot_to_image(page)
        self.agent.save_screenshot(baseline, self.run_dir, "zoom_baseline")

        yield self._progress("Applying 200% zoom via browser scale factor...")

        # Use CDP to set page scale factor to 2x (true browser zoom)
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 2})
        await asyncio.sleep(0.5)

        # Also check for horizontal scrollbar (reflow test)
        scroll_info = await page.evaluate("""() => ({
            scrollWidth: document.documentElement.scrollWidth,
            clientWidth: document.documentElement.clientWidth,
            hasHorizontalScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth + 5,
        })""")

        yield self._progress("Taking 200% zoom screenshot for analysis...")
        zoomed = await self.agent.screenshot_to_image(page)
        screenshot_path = self.agent.save_screenshot(zoomed, self.run_dir, "zoom_200pct")
        screenshot_b64 = self.agent.image_to_base64(zoomed)

        yield self._progress("Asking MolmoWeb to analyze zoomed layout...")
        prompt = PROMPT_TEMPLATE.format(task=task)
        analysis = await self.agent.analyze_screenshot(zoomed, prompt)

        # Override model if DOM detects horizontal scroll
        if scroll_info.get("hasHorizontalScroll"):
            analysis["no_horizontal_scroll"] = False
            analysis["result"] = "fail"
            if not analysis.get("failure_reason"):
                analysis["failure_reason"] = (
                    f"Horizontal scroll required at 200% zoom "
                    f"(scrollWidth={scroll_info['scrollWidth']}px, "
                    f"clientWidth={scroll_info['clientWidth']}px). "
                    "Content does not reflow to a single column."
                )
            analysis["wcag_criteria"] = ["1.4.10"]
            analysis["severity"] = "major"
            if not analysis.get("recommendation"):
                analysis["recommendation"] = (
                    "Use responsive CSS (flexbox/grid, max-width, relative units). "
                    "Avoid fixed-width containers. Test with 320px viewport width."
                )

        # Reset zoom
        await cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 1})

        result = TestResult(
            test_id=self.TEST_ID,
            test_name=self.TEST_NAME,
            result=analysis.get("result", "error"),
            wcag_criteria=analysis.get("wcag_criteria", self.WCAG_CRITERIA),
            severity=analysis.get("severity", self.DEFAULT_SEVERITY),
            failure_reason=analysis.get("failure_reason", ""),
            recommendation=analysis.get("recommendation", ""),
            screenshot_path=screenshot_path,
            screenshot_b64=screenshot_b64,
            details={
                "scroll_info": scroll_info,
                "affected_elements": analysis.get("affected_elements", []),
                "text_readable": analysis.get("text_readable"),
                "controls_intact": analysis.get("controls_intact"),
            },
        )
        yield self._result(result)
