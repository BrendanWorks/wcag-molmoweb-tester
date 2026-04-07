"""
WCAG 2.1 Focus Indicator Test
Maps to: 2.4.7 (Focus Visible)

Two-layer check:
  Layer 1 — Programmatic (CSS):
    Inspects computed outline/box-shadow on each focused element.
    Fast, deterministic, catches missing focus styles.

  Layer 2 — Visual (Molmo2 pointing, when available):
    After CSS says "outline exists", asks Molmo2:
      "Point to the element that currently has keyboard focus."
    CSS can lie — outline: 1px solid rgba(255,255,255,0.05) technically
    passes the CSS check but is invisible. If Molmo2 cannot locate the
    focused element within the expected DOM rect, the indicator is
    upgraded from PASS → WARNING (visually insufficient).

    This is the unique contribution of AllenAI's Molmo2 pointing
    capability: catching false positives that pure DOM inspection misses.
"""

import asyncio
from typing import AsyncGenerator, Optional

from tests.base_test import BaseWCAGTest, TestResult

MAX_TABS = 15
POINT_TOLERANCE = 40  # px — how far Molmo2's point can be from the element rect


def _point_in_rect(px: float, py: float, rect: dict, tol: int = POINT_TOLERANCE) -> bool:
    """Return True if (px, py) falls within the element rect + tolerance."""
    return (
        rect["x"] - tol <= px <= rect["x"] + rect["width"] + tol
        and rect["y"] - tol <= py <= rect["y"] + rect["height"] + tol
    )


class FocusIndicatorTest(BaseWCAGTest):
    TEST_ID = "focus_indicator"
    TEST_NAME = "Focus Visibility Check"
    WCAG_CRITERIA = ["2.4.7"]
    DEFAULT_SEVERITY = "major"

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        failures = []
        warnings = []
        steps = []

        using_molmo = self.pointer is not None
        yield self._progress(
            f"Starting focus indicator test "
            f"({'CSS + Molmo2 visual confirmation' if using_molmo else 'CSS only'})..."
        )

        await page.evaluate("document.activeElement && document.activeElement.blur()")
        await asyncio.sleep(0.3)

        for tab_num in range(1, MAX_TABS + 1):
            yield self._progress(f"Checking focus indicator — Tab {tab_num}/{MAX_TABS}...")
            await page.keyboard.press("Tab")
            await asyncio.sleep(0.3)

            focus_info = await page.evaluate("""() => {
                const el = document.activeElement;
                if (!el || el === document.body) return null;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return {
                    tag: el.tagName,
                    text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 60),
                    role: el.getAttribute('role') || '',
                    outlineWidth: style.outlineWidth,
                    outlineStyle: style.outlineStyle,
                    outlineColor: style.outlineColor,
                    boxShadow: style.boxShadow,
                    visible: rect.width > 0 && rect.height > 0,
                    x: rect.x,
                    y: rect.y,
                    width: rect.width,
                    height: rect.height,
                }
            }""")

            if not focus_info or not focus_info.get("visible"):
                continue

            has_outline = (
                focus_info.get("outlineStyle", "none") not in ("none", "")
                and focus_info.get("outlineWidth", "0px") not in ("0px", "0")
            )
            has_shadow = focus_info.get("boxShadow", "none") not in ("none", "")
            css_pass = has_outline or has_shadow

            el_desc = (
                f"<{focus_info['tag']}> '{focus_info['text']}'"
                if focus_info.get("text") else f"<{focus_info['tag']}>"
            )

            screenshot = await self.agent.screenshot_to_image(page)
            screenshot_path = None
            screenshot_b64 = None

            if not css_pass:
                # ── CSS FAIL: no outline, no shadow ──────────────────────────
                screenshot_path = self.agent.save_screenshot(
                    screenshot, self.run_dir, f"focus_fail_tab{tab_num}"
                )
                screenshot_b64 = self.agent.image_to_base64(screenshot)
                analysis = {
                    "result": "fail",
                    "layer": "css",
                    "focus_indicator_visible": False,
                    "focused_element": el_desc,
                    "failure_reason": (
                        f"No visible focus indicator on {el_desc} "
                        f"(outline: {focus_info.get('outlineStyle','none')}, "
                        f"box-shadow: {focus_info.get('boxShadow','none')[:30]})"
                    ),
                    "wcag_criteria": ["2.4.7"],
                    "severity": "major",
                    "recommendation": (
                        "Add :focus { outline: 2px solid #005fcc; outline-offset: 2px; } "
                        "or a visible box-shadow. Never use outline:none without an alternative."
                    ),
                }
                failures.append({
                    "tab": tab_num, "focus_info": focus_info,
                    "analysis": analysis, "screenshot_path": screenshot_path,
                    "screenshot_b64": screenshot_b64,
                })

            elif using_molmo:
                # ── CSS PASS → ask Molmo2 to visually confirm ────────────────
                yield self._progress(
                    f"CSS outline found on {el_desc} — asking Molmo2 to visually confirm..."
                )
                point = await self.pointer.point_to(
                    screenshot,
                    "the element that currently has keyboard focus"
                )

                if point is None:
                    # Molmo2 could not locate the focused element
                    screenshot_path = self.agent.save_screenshot(
                        screenshot, self.run_dir, f"focus_warn_tab{tab_num}"
                    )
                    screenshot_b64 = self.agent.image_to_base64(screenshot)
                    indicator_desc = ""
                    if has_outline:
                        indicator_desc = (
                            f"outline: {focus_info['outlineWidth']} "
                            f"{focus_info['outlineStyle']} {focus_info['outlineColor']}"
                        )
                    elif has_shadow:
                        indicator_desc = f"box-shadow: {focus_info['boxShadow'][:50]}"

                    analysis = {
                        "result": "warning",
                        "layer": "molmo2_visual",
                        "focus_indicator_visible": False,
                        "focused_element": el_desc,
                        "css_indicator": indicator_desc,
                        "molmo2_point": None,
                        "failure_reason": (
                            f"CSS reports focus indicator ({indicator_desc}) on {el_desc}, "
                            f"but Molmo2 could not locate the focused element visually. "
                            f"The indicator may be present but visually insufficient "
                            f"(too low contrast, too thin, or obscured). "
                            f"Note: if this is a skip-navigation link that appears off-screen "
                            f"until focused, this warning may not apply."
                        ),
                        "wcag_criteria": ["2.4.7"],
                        "severity": "major",
                        "recommendation": (
                            "Ensure the focus indicator has at least 3:1 contrast against "
                            "adjacent colors and is at least 2px thick. "
                            "A common issue: outline color matches the background."
                        ),
                    }
                    warnings.append({
                        "tab": tab_num, "focus_info": focus_info,
                        "analysis": analysis, "screenshot_path": screenshot_path,
                        "screenshot_b64": screenshot_b64,
                    })

                else:
                    px, py = point
                    in_rect = _point_in_rect(px, py, focus_info)
                    indicator_desc = ""
                    if has_outline:
                        indicator_desc = (
                            f"outline: {focus_info['outlineWidth']} "
                            f"{focus_info['outlineStyle']} {focus_info['outlineColor']}"
                        )
                    elif has_shadow:
                        indicator_desc = f"box-shadow: {focus_info['boxShadow'][:50]}"

                    if in_rect:
                        analysis = {
                            "result": "pass",
                            "layer": "molmo2_visual",
                            "focus_indicator_visible": True,
                            "focused_element": el_desc,
                            "css_indicator": indicator_desc,
                            "molmo2_point": {"x": round(px), "y": round(py)},
                            "failure_reason": "",
                            "recommendation": "",
                            "wcag_criteria": ["2.4.7"],
                            "severity": "minor",
                        }
                    else:
                        # Molmo2 pointed somewhere else — may indicate visual confusion
                        screenshot_path = self.agent.save_screenshot(
                            screenshot, self.run_dir, f"focus_mismatch_tab{tab_num}"
                        )
                        screenshot_b64 = self.agent.image_to_base64(screenshot)
                        analysis = {
                            "result": "warning",
                            "layer": "molmo2_visual",
                            "focus_indicator_visible": False,
                            "focused_element": el_desc,
                            "css_indicator": indicator_desc,
                            "molmo2_point": {"x": round(px), "y": round(py)},
                            "failure_reason": (
                                f"CSS indicator found on {el_desc} but Molmo2 pointed to "
                                f"({round(px)},{round(py)}) — outside element bounds "
                                f"({focus_info['x']:.0f},{focus_info['y']:.0f} "
                                f"{focus_info['width']:.0f}×{focus_info['height']:.0f}px). "
                                f"Focus indicator may be visually ambiguous."
                            ),
                            "wcag_criteria": ["2.4.7"],
                            "severity": "minor",
                            "recommendation": (
                                "Increase focus indicator contrast and size so it is "
                                "unambiguously associated with the focused element."
                            ),
                        }
                        warnings.append({
                            "tab": tab_num, "focus_info": focus_info,
                            "analysis": analysis, "screenshot_path": screenshot_path,
                            "screenshot_b64": screenshot_b64,
                        })

            else:
                # ── CSS PASS, no Molmo2 ───────────────────────────────────────
                indicator = []
                if has_outline:
                    indicator.append(
                        f"outline: {focus_info['outlineWidth']} "
                        f"{focus_info['outlineStyle']} {focus_info['outlineColor']}"
                    )
                if has_shadow:
                    indicator.append(f"box-shadow: {focus_info['boxShadow'][:60]}")
                analysis = {
                    "result": "pass",
                    "layer": "css",
                    "focus_indicator_visible": True,
                    "focused_element": el_desc,
                    "indicator": "; ".join(indicator),
                    "failure_reason": "",
                    "recommendation": "",
                    "wcag_criteria": ["2.4.7"],
                    "severity": "minor",
                }

            steps.append({
                "tab": tab_num, "focus_info": focus_info, "analysis": analysis,
                "screenshot_path": screenshot_path,
            })

            if tab_num > 5 and focus_info.get("y", 999) < 50:
                yield self._progress("Focus cycled back to top — done.")
                break

        # ── Summary screenshot ────────────────────────────────────────────────
        summary = await self.agent.screenshot_to_image(page)
        summary_path = self.agent.save_screenshot(summary, self.run_dir, "focus_summary")
        summary_b64 = self.agent.image_to_base64(summary)

        # Hard failures take priority over Molmo2 warnings
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
                screenshot_path=worst.get("screenshot_path") or summary_path,
                screenshot_b64=worst.get("screenshot_b64") or summary_b64,
                details={
                    "steps": steps,
                    "failure_count": len(failures),
                    "molmo2_warnings": len(warnings),
                    "molmo2_used": using_molmo,
                },
            )
        elif warnings:
            worst = warnings[0]
            a = worst["analysis"]
            result = TestResult(
                test_id=self.TEST_ID,
                test_name=self.TEST_NAME,
                result="warning",
                wcag_criteria=a.get("wcag_criteria", self.WCAG_CRITERIA),
                severity=a.get("severity", "minor"),
                failure_reason=a.get("failure_reason", ""),
                recommendation=a.get("recommendation", ""),
                screenshot_path=worst.get("screenshot_path") or summary_path,
                screenshot_b64=worst.get("screenshot_b64") or summary_b64,
                details={
                    "steps": steps,
                    "molmo2_warnings": len(warnings),
                    "molmo2_used": using_molmo,
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
                details={
                    "steps": steps,
                    "tabs_tested": len(steps),
                    "molmo2_used": using_molmo,
                },
            )

        yield self._result(result)
