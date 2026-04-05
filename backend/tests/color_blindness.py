"""
WCAG 2.1 Color-Only Dependency Test
Maps to: 1.4.1 (Use of Color), 1.4.3 (Contrast Minimum)

Applies a Deuteranopia (red-green color blindness) CSS filter,
then asks MolmoWeb to describe the interface WITHOUT using color words.
Flags any element that can only be distinguished by color.
"""

import asyncio
from typing import AsyncGenerator

from tests.base_test import BaseWCAGTest, TestResult

# SVG-based Deuteranopia color matrix filter
DEUTERANOPIA_CSS = """
html {
  filter: url("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'><filter id='d'><feColorMatrix type='matrix' values='0.367 0.861 -0.228 0 0  0.280 0.673 0.047 0 0  -0.012 0.043 0.969 0 0  0 0 0 1 0'/></filter></svg>#d") !important;
}
"""

PROMPT_TEMPLATE = """This screenshot has a color blindness filter applied (Deuteranopia / red-green).

Look at the page and answer:
1. Can you tell what every button, link, and form field does WITHOUT relying on color?
2. Are there any elements where color is the ONLY way to understand their meaning?
3. Is any text hard to read because of low contrast?

Give your answer as JSON:
- "elements_identified_without_color": true or false
- "color_only_elements": list any elements that rely only on color, or empty list []
- "contrast_issues": list any hard-to-read text, or empty list []
- "result": "pass" if everything is clear without color, "fail" if some elements rely on color alone
- "failure_reason": describe problems, or "" if none
- "wcag_criteria": ["1.4.1"]
- "severity": "major" if important info is lost, "minor" if cosmetic
- "recommendation": suggest a fix, or "" if none needed"""


class ColorBlindnessTest(BaseWCAGTest):
    TEST_ID = "color_blindness"
    TEST_NAME = "Color-Blindness Simulation"
    WCAG_CRITERIA = ["1.4.1", "1.4.3"]
    DEFAULT_SEVERITY = "major"

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        yield self._progress("Capturing baseline screenshot...")
        baseline = await self.agent.screenshot_to_image(page)
        self.agent.save_screenshot(baseline, self.run_dir, "color_baseline")

        yield self._progress("Injecting Deuteranopia (red-green color blindness) filter...")
        await page.evaluate(f"""() => {{
            const style = document.createElement('style');
            style.id = '__wcag_deuteranopia__';
            style.textContent = `{DEUTERANOPIA_CSS}`;
            document.head.appendChild(style);
        }}""")
        await asyncio.sleep(0.5)

        yield self._progress("Taking colorblind-simulated screenshot...")
        cb_screenshot = await self.agent.screenshot_to_image(page)
        screenshot_path = self.agent.save_screenshot(
            cb_screenshot, self.run_dir, "color_deuteranopia"
        )
        screenshot_b64 = self.agent.image_to_base64(cb_screenshot)

        yield self._progress("Asking MolmoWeb to identify color-only dependencies...")
        prompt = PROMPT_TEMPLATE.format(task=task)
        analysis = await self.agent.analyze_screenshot(cb_screenshot, prompt)

        # Remove filter
        await page.evaluate("""() => {
            const el = document.getElementById('__wcag_deuteranopia__');
            if (el) el.remove();
        }""")

        color_only = analysis.get("color_only_elements", [])
        contrast_issues = analysis.get("contrast_issues", [])

        if color_only or contrast_issues:
            analysis["result"] = "fail"
            if not analysis.get("failure_reason"):
                parts = []
                if color_only:
                    parts.append(f"Color-only elements: {', '.join(color_only)}")
                if contrast_issues:
                    parts.append(f"Contrast issues: {', '.join(contrast_issues)}")
                analysis["failure_reason"] = ". ".join(parts)
            if not analysis.get("recommendation"):
                analysis["recommendation"] = (
                    "Add non-color indicators (icons, labels, patterns, text) alongside color. "
                    "Ensure text meets 4.5:1 contrast ratio (3:1 for large text)."
                )

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
                "color_only_elements": color_only,
                "contrast_issues": contrast_issues,
            },
        )
        yield self._result(result)
