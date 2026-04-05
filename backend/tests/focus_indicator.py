"""
WCAG 2.1 Focus Indicator Test
Maps to: 2.4.7 (Focus Visible), 2.4.3 (Focus Order)

Tabs through each element, captures a screenshot, asks MolmoWeb
whether the focus ring/indicator is clearly visible and well-placed.
"""

import asyncio
from typing import AsyncGenerator

from tests.base_test import BaseWCAGTest, TestResult

PROMPT_TEMPLATE = """You are a WCAG 2.1 Level AA accessibility auditor testing focus indicators.

Tab was pressed and an element now has keyboard focus. Look at the screenshot carefully.

1. Locate the focused element. Is there a visible focus indicator?
   (Look for: colored outline, ring, highlight, underline, box-shadow, background change)
2. Is the focus indicator high-contrast and clearly distinguishable from the surrounding content?
3. Does the focus indicator have sufficient size (at least 2px thick outline)?
4. Is the focused element the one you would logically expect to be next in reading order?

Respond ONLY with this JSON (no other text):
{{
  "focus_indicator_visible": true,
  "focus_indicator_description": "describe what the focus indicator looks like",
  "sufficient_contrast": true,
  "logical_order": true,
  "focused_element": "description of the element that has focus",
  "result": "pass|fail",
  "failure_reason": "if fail, explain exactly what is missing or wrong (empty string if pass)",
  "wcag_criteria": ["2.4.7"],
  "severity": "critical|major|minor",
  "recommendation": "specific CSS fix if failed (empty string if pass)"
}}"""

MAX_TABS = 15


class FocusIndicatorTest(BaseWCAGTest):
    TEST_ID = "focus_indicator"
    TEST_NAME = "Focus Visibility Check"
    WCAG_CRITERIA = ["2.4.7", "2.4.3"]
    DEFAULT_SEVERITY = "major"

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        failures = []
        steps = []

        yield self._progress("Starting focus indicator test...")
        await page.evaluate("document.activeElement && document.activeElement.blur()")
        await asyncio.sleep(0.3)

        for tab_num in range(1, MAX_TABS + 1):
            yield self._progress(f"Checking focus indicator on Tab {tab_num}/{MAX_TABS}...")

            await page.keyboard.press("Tab")
            await asyncio.sleep(0.4)

            focus_info = await page.evaluate("""() => {
                const el = document.activeElement;
                if (!el || el === document.body) return null;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return {
                    tag: el.tagName,
                    text: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 60),
                    outlineWidth: style.outlineWidth,
                    outlineStyle: style.outlineStyle,
                    outlineColor: style.outlineColor,
                    boxShadow: style.boxShadow,
                    border: style.border,
                    visible: rect.width > 0 && rect.height > 0,
                }
            }""")

            if not focus_info or not focus_info.get("visible"):
                continue

            screenshot = await self.agent.screenshot_to_image(page)
            screenshot_path = self.agent.save_screenshot(
                screenshot, self.run_dir, f"focus_tab{tab_num}"
            )
            screenshot_b64 = self.agent.image_to_base64(screenshot)

            analysis = await self.agent.analyze_screenshot(screenshot, PROMPT_TEMPLATE)

            # DOM-level check as override
            has_outline = (
                focus_info.get("outlineStyle", "none") not in ("none", "")
                and focus_info.get("outlineWidth", "0px") not in ("0px", "0")
            )
            has_shadow = focus_info.get("boxShadow", "none") not in ("none", "")
            if not has_outline and not has_shadow:
                analysis["focus_indicator_visible"] = False
                analysis["result"] = "fail"
                analysis["failure_reason"] = (
                    f"No CSS focus indicator on <{focus_info['tag']}> "
                    f"'{focus_info['text']}' (outline: none, box-shadow: none)"
                )
                analysis["wcag_criteria"] = ["2.4.7"]
                analysis["severity"] = "major"
                analysis["recommendation"] = (
                    "Add :focus { outline: 2px solid #005fcc; outline-offset: 2px; } "
                    "or a visible box-shadow. Never use outline: none without an alternative."
                )

            step = {
                "tab": tab_num,
                "focus_info": focus_info,
                "analysis": analysis,
                "screenshot_path": screenshot_path,
                "screenshot_b64": screenshot_b64,
            }
            steps.append(step)

            if analysis.get("result") == "fail":
                failures.append(step)

            if tab_num > 5 and focus_info and focus_info.get("tag") == "BODY":
                break

        if failures:
            worst = failures[0]
            a = worst["analysis"]
            result = TestResult(
                test_id=self.TEST_ID,
                test_name=self.TEST_NAME,
                result="fail",
                wcag_criteria=a.get("wcag_criteria", self.WCAG_CRITERIA),
                severity=a.get("severity", self.DEFAULT_SEVERITY),
                failure_reason=a.get("failure_reason", ""),
                recommendation=a.get("recommendation", ""),
                screenshot_path=worst["screenshot_path"],
                screenshot_b64=worst["screenshot_b64"],
                details={"steps": steps, "failure_count": len(failures)},
            )
        else:
            last = steps[-1] if steps else {}
            result = TestResult(
                test_id=self.TEST_ID,
                test_name=self.TEST_NAME,
                result="pass",
                wcag_criteria=self.WCAG_CRITERIA,
                severity="minor",
                screenshot_path=last.get("screenshot_path"),
                screenshot_b64=last.get("screenshot_b64"),
                details={"steps": steps, "tabs_tested": len(steps)},
            )

        yield self._result(result)
