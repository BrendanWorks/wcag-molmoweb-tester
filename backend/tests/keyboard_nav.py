"""
WCAG 2.1 Keyboard Navigation Test
Maps to: 2.1.1 (Keyboard), 2.1.2 (No Keyboard Trap), 2.4.3 (Focus Order)

Drives Tab/Enter/arrow keys through the page, checks that every
interactive element is reachable and that there are no keyboard traps.
"""

import asyncio
from pathlib import Path
from typing import AsyncGenerator

from tests.base_test import BaseWCAGTest, TestResult

PROMPT_TEMPLATE = """The user just pressed Tab on this web page. Look at the screenshot.

Answer these questions:
1. What element has keyboard focus right now? Describe it.
2. Is there a visible focus indicator (outline, highlight, or glow) around it?
3. What type of element is it (button, link, input, etc.)?

Give your answer as JSON:
- "focused_element": describe the focused element
- "focus_visible": true or false
- "element_type": "button", "link", "input", or "other"
- "logical_order": true if focus is in a sensible reading order
- "result": "pass" if focus is visible and logical, "fail" if not
- "failure_reason": explain any problem, or "" if none
- "wcag_criteria": ["2.1.1", "2.4.3"]
- "severity": "critical" if no focus visible, "major" if order is wrong, "minor" otherwise
- "recommendation": suggest a fix, or "" if none needed"""

TRAP_PROMPT = """You are a WCAG 2.1 Level AA accessibility auditor.

The user pressed Tab {tab_count} times in a row and focus has not moved to a new element.
This may indicate a keyboard trap (WCAG 2.1.2).

Screenshot shows the current page state.

Respond ONLY with this JSON:
{{
  "trapped": true,
  "focused_element": "description of element that appears stuck",
  "result": "fail",
  "failure_reason": "Keyboard trap detected: focus did not move after multiple Tab presses",
  "wcag_criteria": ["2.1.2"],
  "severity": "critical",
  "recommendation": "Ensure all modal dialogs, widgets, and custom components allow Tab to exit"
}}"""

MAX_TABS = 20


class KeyboardNavTest(BaseWCAGTest):
    TEST_ID = "keyboard_nav"
    TEST_NAME = "Keyboard-Only Navigation"
    WCAG_CRITERIA = ["2.1.1", "2.1.2", "2.4.3"]
    DEFAULT_SEVERITY = "critical"

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        failures = []
        steps = []
        prev_element = None
        stuck_count = 0

        yield self._progress("Starting keyboard navigation test...")

        # Reset focus to top of page
        await page.evaluate("document.activeElement && document.activeElement.blur()")
        await asyncio.sleep(0.3)

        for tab_num in range(1, MAX_TABS + 1):
            yield self._progress(f"Tab press {tab_num}/{MAX_TABS}...")

            await page.keyboard.press("Tab")
            await asyncio.sleep(0.4)

            # Get focused element info from DOM
            focus_info = await page.evaluate("""() => {
                const el = document.activeElement;
                if (!el || el === document.body) return null;
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return {
                    tag: el.tagName,
                    text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 80),
                    role: el.getAttribute('role') || '',
                    type: el.getAttribute('type') || '',
                    outline: style.outlineWidth,
                    outlineColor: style.outlineColor,
                    outlineStyle: style.outlineStyle,
                    boxShadow: style.boxShadow,
                    visible: rect.width > 0 && rect.height > 0,
                    x: rect.x,
                    y: rect.y,
                }
            }""")

            # Trap detection: same element 3 tabs in a row
            element_key = str(focus_info)
            if element_key == prev_element:
                stuck_count += 1
            else:
                stuck_count = 0
            prev_element = element_key

            if stuck_count >= 3:
                screenshot = await self.agent.screenshot_to_image(page)
                screenshot_path = self.agent.save_screenshot(
                    screenshot, self.run_dir, f"keyboard_trap_tab{tab_num}"
                )
                screenshot_b64 = self.agent.image_to_base64(screenshot)

                trap_result = TestResult(
                    test_id=self.TEST_ID,
                    test_name=self.TEST_NAME,
                    result="fail",
                    wcag_criteria=["2.1.2"],
                    severity="critical",
                    failure_reason="Keyboard trap detected: focus did not move after 3 consecutive Tab presses",
                    recommendation="Ensure all interactive widgets allow Tab/Shift+Tab to exit. Check modal dialogs, date pickers, and custom JS components.",
                    screenshot_path=screenshot_path,
                    screenshot_b64=screenshot_b64,
                )
                yield self._result(trap_result)
                return

            screenshot = await self.agent.screenshot_to_image(page)
            screenshot_path = self.agent.save_screenshot(
                screenshot, self.run_dir, f"keyboard_tab{tab_num}"
            )
            screenshot_b64 = self.agent.image_to_base64(screenshot)

            prompt = PROMPT_TEMPLATE.format(task=task)
            analysis = await self.agent.analyze_screenshot(screenshot, prompt)

            # Augment model analysis with DOM-derived data
            if focus_info:
                # Hard-check: no outline AND no box-shadow = invisible focus
                has_outline = (
                    focus_info.get("outlineStyle", "none") != "none"
                    and focus_info.get("outlineWidth", "0px") not in ("0px", "0")
                )
                has_shadow = focus_info.get("boxShadow", "none") not in ("none", "")
                if not has_outline and not has_shadow:
                    analysis["focus_visible"] = False
                    analysis["result"] = "fail"
                    analysis["failure_reason"] = (
                        f"No visible focus indicator on <{focus_info['tag']}> "
                        f"element: '{focus_info['text']}'"
                    )
                    analysis["wcag_criteria"] = ["2.4.7"]
                    analysis["severity"] = "major"
                    analysis["recommendation"] = (
                        "Add a visible :focus style (outline, box-shadow, or background change) "
                        "with at least 3:1 contrast against adjacent colors."
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

            # If we've cycled back (focus returned to first element), we're done
            if tab_num > 5 and focus_info and focus_info.get("y", 999) < 100:
                yield self._progress("Focus cycled back to top — navigation complete.")
                break

        overall_result = "fail" if failures else "pass"

        if failures:
            worst = failures[0]
            analysis = worst["analysis"]
            final = TestResult(
                test_id=self.TEST_ID,
                test_name=self.TEST_NAME,
                result="fail",
                wcag_criteria=analysis.get("wcag_criteria", self.WCAG_CRITERIA),
                severity=analysis.get("severity", self.DEFAULT_SEVERITY),
                failure_reason=analysis.get("failure_reason", "Keyboard navigation issues found"),
                recommendation=analysis.get("recommendation", ""),
                screenshot_path=worst["screenshot_path"],
                screenshot_b64=worst["screenshot_b64"],
                details={"steps": steps, "failure_count": len(failures)},
            )
        else:
            last = steps[-1] if steps else {}
            final = TestResult(
                test_id=self.TEST_ID,
                test_name=self.TEST_NAME,
                result="pass",
                wcag_criteria=self.WCAG_CRITERIA,
                severity="minor",
                failure_reason="",
                recommendation="",
                screenshot_path=last.get("screenshot_path"),
                screenshot_b64=last.get("screenshot_b64"),
                details={"steps": steps, "tabs_tested": len(steps)},
            )

        yield self._result(final)
