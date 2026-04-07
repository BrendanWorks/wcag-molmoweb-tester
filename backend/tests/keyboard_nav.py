"""
WCAG 2.1 Keyboard Navigation Test — Fully Programmatic
Maps to: 2.1.1 (Keyboard), 2.1.2 (No Keyboard Trap), 2.4.3 (Focus Order)

Drives Tab through the page, inspects computed CSS for each focused element.
No VLM — DOM is the sole authority for pass/fail.
"""

import asyncio
from typing import AsyncGenerator

from tests.base_test import BaseWCAGTest, TestResult

MAX_TABS = 10

# JS checks run once against the static DOM
KEYBOARD_STATIC_JS = """
() => {
    const issues = [];

    // 1. javascript: href links — keyboard Enter activates href, not the JS
    //    but screen readers and some ATs won't follow them reliably.
    //    More critically: links with ONLY onclick and href="#" / no href are mouse-traps.
    const jsLinks = Array.from(document.querySelectorAll('a[href]')).filter(a => {
        return a.getAttribute('href').trim().toLowerCase().startsWith('javascript:');
    });
    if (jsLinks.length > 0) {
        issues.push({
            criterion: '2.1.1',
            severity: 'major',
            description: `${jsLinks.length} link(s) use javascript: href — unreliable for keyboard/AT users.`,
            examples: jsLinks.slice(0, 3).map(a => (a.innerText || a.href).trim().slice(0, 60)),
        });
    }

    // 2. Clickable non-interactive elements with no keyboard role or tabindex
    const mouseOnlyEls = Array.from(document.querySelectorAll('div,span,td,li')).filter(el => {
        const hasClick = el.onclick || el.getAttribute('onclick');
        const role = el.getAttribute('role') || '';
        const tab = el.getAttribute('tabindex');
        const interactive = ['button','link','menuitem','option','tab','checkbox','radio'].includes(role);
        return hasClick && !interactive && tab === null;
    });
    if (mouseOnlyEls.length > 0) {
        issues.push({
            criterion: '2.1.1',
            severity: 'major',
            description: `${mouseOnlyEls.length} element(s) have click handlers but are not keyboard-reachable (no role + tabindex).`,
            examples: mouseOnlyEls.slice(0, 3).map(el => (el.innerText || el.tagName).trim().slice(0, 60)),
        });
    }

    // 3. onmouseover without onfocus equivalent (mouse-only hover interactions)
    const hoverOnly = Array.from(document.querySelectorAll('[onmouseover]')).filter(el => {
        return !el.getAttribute('onfocus') && !el.getAttribute('onmouseenter');
    });
    if (hoverOnly.length > 0) {
        issues.push({
            criterion: '2.1.1',
            severity: 'minor',
            description: `${hoverOnly.length} element(s) use onmouseover without an onfocus equivalent.`,
            examples: hoverOnly.slice(0, 3).map(el => (el.innerText || el.tagName).trim().slice(0, 60)),
        });
    }

    // 4. Missing skip navigation link (2.4.1)
    const skipLinks = Array.from(document.querySelectorAll('a')).filter(a => {
        const text = (a.innerText || '').toLowerCase();
        const href = (a.getAttribute('href') || '');
        return (text.includes('skip') || text.includes('jump')) && href.startsWith('#');
    });
    if (skipLinks.length === 0) {
        issues.push({
            criterion: '2.4.1',
            severity: 'minor',
            description: 'No skip navigation link found. Users must Tab through all repeated navigation on every page.',
            examples: [],
        });
    }

    return issues;
}
"""


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

        # ── Static DOM checks (JS-only links, mouse-only handlers, skip nav) ──
        yield self._progress("Checking for JS-only links and mouse-only handlers...")
        static_issues = await page.evaluate(KEYBOARD_STATIC_JS)
        static_failures = [i for i in static_issues if i.get("severity") == "major"]
        static_warnings = [i for i in static_issues if i.get("severity") == "minor"]

        await page.evaluate("document.activeElement && document.activeElement.blur()")
        await asyncio.sleep(0.3)

        for tab_num in range(1, MAX_TABS + 1):
            yield self._progress(f"Tab press {tab_num}/{MAX_TABS}...")
            await page.keyboard.press("Tab")
            await asyncio.sleep(0.4)

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
                    outlineWidth: style.outlineWidth,
                    outlineColor: style.outlineColor,
                    outlineStyle: style.outlineStyle,
                    boxShadow: style.boxShadow,
                    visible: rect.width > 0 && rect.height > 0,
                    x: rect.x,
                    y: rect.y,
                }
            }""")

            # Trap detection: same element 3+ tabs in a row
            element_key = str(focus_info)
            if element_key == prev_element:
                stuck_count += 1
            else:
                stuck_count = 0
            prev_element = element_key

            if stuck_count >= 3:
                screenshot = await self.agent.screenshot_to_image(page)
                sp = self.agent.save_screenshot(screenshot, self.run_dir, f"keyboard_trap_{tab_num}")
                sb64 = self.agent.image_to_base64(screenshot)
                yield self._result(TestResult(
                    test_id=self.TEST_ID,
                    test_name=self.TEST_NAME,
                    result="fail",
                    wcag_criteria=["2.1.2"],
                    severity="critical",
                    failure_reason="Keyboard trap: focus did not move after 3 consecutive Tab presses.",
                    recommendation=(
                        "Ensure all custom widgets, modals, and date pickers "
                        "allow Tab/Shift+Tab to exit."
                    ),
                    screenshot_path=sp,
                    screenshot_b64=sb64,
                ))
                return

            if not focus_info or not focus_info.get("visible"):
                continue

            has_outline = (
                focus_info.get("outlineStyle", "none") not in ("none", "")
                and focus_info.get("outlineWidth", "0px") not in ("0px", "0")
            )
            has_shadow = focus_info.get("boxShadow", "none") not in ("none", "")
            el_desc = (
                f"<{focus_info['tag']}> '{focus_info['text']}'"
                if focus_info.get("text")
                else f"<{focus_info['tag']}>"
            )

            # Note: focus indicator quality is owned by focus_indicator test (2.4.7).
            # Here we only record whether the element received focus at all (2.1.1).
            analysis = {
                "result": "pass",
                "focused_element": el_desc,
                "has_focus_style": has_outline or has_shadow,
            }

            steps.append({"tab": tab_num, "focus_info": focus_info, "analysis": analysis})

            if tab_num > 5 and focus_info.get("y", 999) < 100:
                yield self._progress("Focus cycled back to top — done.")
                break

        summary = await self.agent.screenshot_to_image(page)
        summary_path = self.agent.save_screenshot(summary, self.run_dir, "keyboard_summary")
        summary_b64 = self.agent.image_to_base64(summary)

        all_failures = static_failures  # tab-trap failures come from early return above
        all_warnings = static_warnings

        if all_failures:
            # Consolidate all static failures into one report
            issue = static_failures[0]
            failure_reason = "; ".join(i["description"] for i in static_failures[:3])
            all_examples = []
            for i in static_failures[:2]:
                all_examples.extend(i.get("examples", [])[:2])
            if all_examples:
                failure_reason += f" — e.g.: {'; '.join(all_examples[:3])}"
            wcag = list(dict.fromkeys(i["criterion"] for i in static_failures))
            severity = "major"
            sp, sb64 = summary_path, summary_b64

            result = TestResult(
                test_id=self.TEST_ID,
                test_name=self.TEST_NAME,
                result="fail",
                wcag_criteria=wcag,
                severity=severity,
                failure_reason=failure_reason,
                recommendation=(
                    "Ensure all interactive elements are operable by keyboard alone. "
                    "Replace javascript: hrefs with proper event handlers. "
                    "Add tabindex + role to custom clickable elements. "
                    "Add a skip navigation link as the first focusable element."
                ),
                screenshot_path=sp,
                screenshot_b64=sb64,
                details={
                    "steps": steps,
                    "focus_failures": len(failures),
                    "static_failures": static_failures,
                    "static_warnings": static_warnings,
                },
            )
        elif all_warnings:
            issue = all_warnings[0]
            result = TestResult(
                test_id=self.TEST_ID,
                test_name=self.TEST_NAME,
                result="warning",
                wcag_criteria=["2.4.1"],
                severity="minor",
                failure_reason="; ".join(i["description"] for i in all_warnings),
                recommendation=(
                    "Add a visible 'Skip to main content' link as the first focusable element. "
                    "Replace mouse-only hover interactions with keyboard-accessible equivalents."
                ),
                screenshot_path=summary_path,
                screenshot_b64=summary_b64,
                details={
                    "steps": steps,
                    "static_warnings": static_warnings,
                },
            )
        else:
            result = TestResult(
                test_id=self.TEST_ID,
                test_name=self.TEST_NAME,
                result="pass",
                wcag_criteria=self.WCAG_CRITERIA,
                severity="minor",
                failure_reason="",
                recommendation="",
                screenshot_path=summary_path,
                screenshot_b64=summary_b64,
                details={"steps": steps, "tabs_tested": len(steps)},
            )

        yield self._result(result)
