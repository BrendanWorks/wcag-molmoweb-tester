"""
WCAG Focus Visibility — 2.4.7

Layer 1 (programmatic): CSS outline / box-shadow inspection on each focused element.
Layer 2 (visual): MolmoWeb-8B attempts to locate the focused element and describe
                  whether the indicator is actually perceivable — catching false
                  positives that DOM inspection cannot (near-invisible outlines).

MolmoWeb-8B replaces the old Molmo2-4B pointer here. Same pointing logic, same
coordinate format (<point x="X" y="Y">), but 8B has better visual understanding.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Optional

from app.wcag_checks.base import BaseWCAGTest, TestResult


MAX_TABS = 15
MAX_MOLMO_CALLS = 5   # cap GPU calls per page — each takes ~30-50s
POINT_TOLERANCE = 40  # px tolerance for Molmo point-in-element check


def _point_in_rect(px: float, py: float, rect: dict, tol: int = POINT_TOLERANCE) -> bool:
    return (
        rect["x"] - tol <= px <= rect["x"] + rect["width"] + tol
        and rect["y"] - tol <= py <= rect["y"] + rect["height"] + tol
    )


class FocusIndicatorTest(BaseWCAGTest):
    TEST_ID = "focus_indicator"
    TEST_NAME = "Focus Visibility Check"
    WCAG_CRITERIA = ["2.4.7"]
    DEFAULT_SEVERITY = "major"
    # Per-element question — formatted inline in the run() loop
    MOLMO_QUESTION = None  # overridden per-call

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        failures = []
        warnings = []
        steps = []
        molmo_calls = 0
        molmo_logs: list[str] = []

        yield self._progress("Starting focus indicator test (CSS + MolmoWeb visual)...")

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
                const rect  = el.getBoundingClientRect();
                return {
                    tag:          el.tagName,
                    text:         (el.innerText||el.value||el.getAttribute('aria-label')||'').trim().slice(0,60),
                    role:         el.getAttribute('role')||'',
                    outlineWidth: style.outlineWidth,
                    outlineStyle: style.outlineStyle,
                    outlineColor: style.outlineColor,
                    boxShadow:    style.boxShadow,
                    visible:      rect.width>0 && rect.height>0,
                    x: rect.x, y: rect.y, width: rect.width, height: rect.height,
                }
            }""")

            if not focus_info or not focus_info.get("visible"):
                continue

            has_outline = (
                focus_info.get("outlineStyle", "none") not in ("none", "")
                and focus_info.get("outlineWidth", "0px") not in ("0px", "0")
            )
            has_shadow = focus_info.get("boxShadow", "none") not in ("none", "")
            css_pass   = has_outline or has_shadow

            el_desc = (
                f"<{focus_info['tag']}> '{focus_info['text']}'"
                if focus_info.get("text") else f"<{focus_info['tag']}>"
            )

            screenshot    = await self.analyzer.screenshot_to_image(page)
            screenshot_path = screenshot_b64 = None

            if not css_pass:
                screenshot_path = self.analyzer.save_screenshot(
                    screenshot, self.run_dir, f"focus_fail_tab{tab_num}"
                )
                screenshot_b64 = self.analyzer.image_to_base64(screenshot)
                analysis = {
                    "result": "fail", "layer": "css",
                    "focus_indicator_visible": False,
                    "focused_element": el_desc,
                    "failure_reason": (
                        f"No visible focus indicator on {el_desc} "
                        f"(outline: {focus_info.get('outlineStyle','none')}, "
                        f"box-shadow: {focus_info.get('boxShadow','none')[:30]})"
                    ),
                    "wcag_criteria": ["2.4.7"], "severity": "major",
                    "recommendation": (
                        "Add :focus { outline: 2px solid #005fcc; outline-offset: 2px; } "
                        "or a visible box-shadow. Never use outline:none without an alternative."
                    ),
                }
                failures.append({
                    "tab": tab_num, "focus_info": focus_info, "analysis": analysis,
                    "screenshot_path": screenshot_path, "screenshot_b64": screenshot_b64,
                })

            elif molmo_calls < MAX_MOLMO_CALLS:
                molmo_calls += 1
                yield self._progress(
                    f"CSS outline found on {el_desc} — MolmoWeb visual confirmation "
                    f"({molmo_calls}/{MAX_MOLMO_CALLS})..."
                )
                question = f"Is there a visible focus outline or ring around {el_desc}? Answer yes or no."
                try:
                    point = await asyncio.wait_for(
                        self.analyzer.point_to(screenshot, f"focus indicator on {el_desc}"),
                        timeout=self.MOLMO_TIMEOUT,
                    )
                    molmo_raw = await asyncio.wait_for(
                        self.analyzer.analyze(screenshot, question),
                        timeout=self.MOLMO_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    yield self._progress(f"MolmoWeb timed out on tab {tab_num}.")
                    point = None
                    molmo_raw = "[timed out]"

                molmo_logs.append(f"tab{tab_num}: {molmo_raw[:100]}")
                indicator_desc = (
                    f"outline: {focus_info['outlineWidth']} {focus_info['outlineStyle']} {focus_info['outlineColor']}"
                    if has_outline else f"box-shadow: {focus_info['boxShadow'][:50]}"
                )

                if point is None:
                    screenshot_path = self.analyzer.save_screenshot(
                        screenshot, self.run_dir, f"focus_warn_tab{tab_num}"
                    )
                    screenshot_b64 = self.analyzer.image_to_base64(screenshot)
                    analysis = {
                        "result": "warning", "layer": "molmo_visual",
                        "focus_indicator_visible": False,
                        "focused_element": el_desc, "css_indicator": indicator_desc,
                        "molmo_point": None,
                        "failure_reason": (
                            f"CSS reports focus indicator ({indicator_desc}) on {el_desc}, "
                            "but MolmoWeb could not locate the focused element visually. "
                            "Indicator may be present but visually insufficient."
                        ),
                        "wcag_criteria": ["2.4.7"], "severity": "major",
                        "recommendation": (
                            "Ensure focus indicator has at least 3:1 contrast against adjacent "
                            "colors and is at least 2px thick."
                        ),
                    }
                    warnings.append({
                        "tab": tab_num, "focus_info": focus_info, "analysis": analysis,
                        "screenshot_path": screenshot_path, "screenshot_b64": screenshot_b64,
                    })
                else:
                    px, py = point
                    in_rect = _point_in_rect(px, py, focus_info)
                    if in_rect:
                        analysis = {
                            "result": "pass", "layer": "molmo_visual",
                            "focus_indicator_visible": True,
                            "focused_element": el_desc, "css_indicator": indicator_desc,
                            "molmo_point": {"x": round(px), "y": round(py)},
                        }
                    else:
                        screenshot_path = self.analyzer.save_screenshot(
                            screenshot, self.run_dir, f"focus_mismatch_tab{tab_num}"
                        )
                        screenshot_b64 = self.analyzer.image_to_base64(screenshot)
                        analysis = {
                            "result": "warning", "layer": "molmo_visual",
                            "focus_indicator_visible": False,
                            "focused_element": el_desc, "css_indicator": indicator_desc,
                            "molmo_point": {"x": round(px), "y": round(py)},
                            "failure_reason": (
                                f"CSS indicator found on {el_desc} but MolmoWeb pointed to "
                                f"({round(px)},{round(py)}) — outside element bounds. "
                                "Focus indicator may be visually ambiguous."
                            ),
                            "wcag_criteria": ["2.4.7"], "severity": "minor",
                            "recommendation": (
                                "Increase focus indicator contrast and size so it is "
                                "unambiguously associated with the focused element."
                            ),
                        }
                        warnings.append({
                            "tab": tab_num, "focus_info": focus_info, "analysis": analysis,
                            "screenshot_path": screenshot_path, "screenshot_b64": screenshot_b64,
                        })
            else:
                indicator = []
                if has_outline:
                    indicator.append(f"outline: {focus_info['outlineWidth']} {focus_info['outlineStyle']} {focus_info['outlineColor']}")
                if has_shadow:
                    indicator.append(f"box-shadow: {focus_info['boxShadow'][:60]}")
                analysis = {
                    "result": "pass", "layer": "css",
                    "focus_indicator_visible": True,
                    "focused_element": el_desc,
                    "indicator": "; ".join(indicator),
                }

            steps.append({"tab": tab_num, "focus_info": focus_info, "analysis": analysis})
            if tab_num > 5 and focus_info.get("y", 999) < 50:
                yield self._progress("Focus cycled back to top — done.")
                break

        summary     = await self.analyzer.screenshot_to_image(page)
        summary_path = self.analyzer.save_screenshot(summary, self.run_dir, "focus_summary")
        summary_b64  = self.analyzer.image_to_base64(summary)
        molmo_combined = " | ".join(molmo_logs)

        if failures:
            worst = failures[0]
            a = worst["analysis"]
            result = TestResult(
                test_id=self.TEST_ID, test_name=self.TEST_NAME,
                result="fail",
                wcag_criteria=a.get("wcag_criteria", self.WCAG_CRITERIA),
                severity=a.get("severity", self.DEFAULT_SEVERITY),
                failure_reason=a.get("failure_reason", ""),
                recommendation=a.get("recommendation", ""),
                screenshot_path=worst.get("screenshot_path") or summary_path,
                screenshot_b64=worst.get("screenshot_b64") or summary_b64,
                molmo_analysis=molmo_combined,
                details={"steps": steps, "failure_count": len(failures), "molmo_warnings": len(warnings)},
            )
        elif warnings:
            worst = warnings[0]
            a = worst["analysis"]
            result = TestResult(
                test_id=self.TEST_ID, test_name=self.TEST_NAME,
                result="warning",
                wcag_criteria=a.get("wcag_criteria", self.WCAG_CRITERIA),
                severity=a.get("severity", "minor"),
                failure_reason=a.get("failure_reason", ""),
                recommendation=a.get("recommendation", ""),
                screenshot_path=worst.get("screenshot_path") or summary_path,
                screenshot_b64=worst.get("screenshot_b64") or summary_b64,
                molmo_analysis=molmo_combined,
                details={"steps": steps, "molmo_warnings": len(warnings)},
            )
        else:
            result = TestResult(
                test_id=self.TEST_ID, test_name=self.TEST_NAME,
                result="pass", wcag_criteria=self.WCAG_CRITERIA, severity="minor",
                screenshot_path=summary_path, screenshot_b64=summary_b64,
                molmo_analysis=molmo_combined,
                details={"steps": steps, "tabs_tested": len(steps)},
            )

        yield self._result(result)
