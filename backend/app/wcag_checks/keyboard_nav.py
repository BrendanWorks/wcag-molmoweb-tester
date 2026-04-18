"""
WCAG Keyboard Navigation — 2.1.1, 2.1.2, 2.4.1, 2.4.3

Layer 1 (programmatic): JS DOM inspection — same logic as PointCheck v1.
Layer 2 (visual):       MolmoWeb-8B confirms skip-nav link visibility.
Layer 3 (agent):        MolmoWebAgentLoop verifies skip-nav is functional
                        (clicks it, checks focus actually jumps to main content)
                        and discovers interactive UI states (dropdowns, modals,
                        nav toggles) to test their keyboard accessibility.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from app.molmo_agent import MolmoWebAgentLoop
from app.wcag_checks.base import BaseWCAGTest, TestResult


MAX_TABS = 10

KEYBOARD_STATIC_JS = """
() => {
    const issues = [];

    const jsLinks = Array.from(document.querySelectorAll('a[href]')).filter(a =>
        a.getAttribute('href').trim().toLowerCase().startsWith('javascript:')
    );
    if (jsLinks.length > 0) {
        issues.push({
            criterion: '2.1.1', severity: 'serious',
            description: `${jsLinks.length} link(s) use javascript: href — unreliable for keyboard/AT users.`,
            examples: jsLinks.slice(0,3).map(a => (a.innerText||a.href).trim().slice(0,120)),
        });
    }

    const mouseOnlyEls = Array.from(document.querySelectorAll('div,span,td,li')).filter(el => {
        const hasClick = el.onclick || el.getAttribute('onclick');
        const role = el.getAttribute('role') || '';
        const tab  = el.getAttribute('tabindex');
        const interactive = ['button','link','menuitem','option','tab','checkbox','radio'].includes(role);
        return hasClick && !interactive && tab === null;
    });
    if (mouseOnlyEls.length > 0) {
        issues.push({
            criterion: '2.1.1', severity: 'serious',
            description: `${mouseOnlyEls.length} element(s) have click handlers but are not keyboard-reachable.`,
            examples: mouseOnlyEls.slice(0,3).map(el => (el.innerText||el.tagName).trim().slice(0,120)),
        });
    }

    const hoverOnly = Array.from(document.querySelectorAll('[onmouseover]')).filter(el =>
        !el.getAttribute('onfocus') && !el.getAttribute('onmouseenter')
    );
    if (hoverOnly.length > 0) {
        issues.push({
            criterion: '2.1.1', severity: 'moderate',
            description: `${hoverOnly.length} element(s) use onmouseover without an onfocus equivalent.`,
            examples: hoverOnly.slice(0,3).map(el => (el.innerText||el.tagName).trim().slice(0,120)),
        });
    }

    const skipLinks = Array.from(document.querySelectorAll('a')).filter(a => {
        const text = (a.innerText||'').toLowerCase();
        const href = a.getAttribute('href') || '';
        return (text.includes('skip') || text.includes('jump')) && href.startsWith('#');
    });
    if (skipLinks.length === 0) {
        issues.push({
            criterion: '2.4.1', severity: 'minor',
            description: 'No skip navigation link found. Users must Tab through all repeated navigation on every page.',
            examples: [],
        });
    }

    const NATIVE_FOCUSABLE = new Set(['A','BUTTON','INPUT','SELECT','TEXTAREA']);
    const scrollableNotFocusable = Array.from(document.querySelectorAll('*')).filter(el => {
        if (el === document.body || el === document.documentElement) return false;
        const s = window.getComputedStyle(el);
        if (!/auto|scroll/.test(s.overflow+' '+s.overflowX+' '+s.overflowY)) return false;
        const hasOverflow = el.scrollHeight > el.clientHeight+2 || el.scrollWidth > el.clientWidth+2;
        if (!hasOverflow) return false;
        const tab = el.getAttribute('tabindex');
        return !NATIVE_FOCUSABLE.has(el.tagName) && (tab===null || parseInt(tab)<0);
    });
    if (scrollableNotFocusable.length > 0) {
        issues.push({
            criterion: '2.1.1', severity: 'serious',
            description: `${scrollableNotFocusable.length} scrollable region(s) are not keyboard accessible.`,
            examples: scrollableNotFocusable.slice(0,3).map(el => {
                const label = (el.getAttribute('aria-label')||el.id||el.className||'').trim().slice(0,40);
                return `<${el.tagName.toLowerCase()}>${label?' "'+label+'"':''} (scroll: ${Math.round(el.scrollHeight)}px / visible: ${Math.round(el.clientHeight)}px)`;
            }),
        });
    }

    const posTabEls = Array.from(document.querySelectorAll('[tabindex]')).filter(el =>
        parseInt(el.getAttribute('tabindex')) > 0
    );
    if (posTabEls.length > 0) {
        issues.push({
            criterion: '2.4.3', severity: 'serious',
            description: `${posTabEls.length} element(s) use positive tabindex values, disrupting natural tab order.`,
            examples: posTabEls.slice(0,3).map(el => {
                const tag   = el.tagName.toLowerCase();
                const label = (el.innerText||el.getAttribute('aria-label')||'').trim().slice(0,40);
                return `<${tag} tabindex="${el.getAttribute('tabindex')}">${label?' "'+label+'"':''}`;
            }),
        });
    }

    return issues;
}
"""


class KeyboardNavTest(BaseWCAGTest):
    TEST_ID = "keyboard_nav"
    TEST_NAME = "Keyboard-Only Navigation"
    WCAG_CRITERIA = ["2.1.1", "2.1.2", "2.4.1", "2.4.3"]
    DEFAULT_SEVERITY = "critical"
    MOLMO_QUESTION = (
        "Where is the skip navigation or skip to main content link on this page? "
        "Describe where it appears at the top of the page."
    )

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        failures = []
        steps = []
        prev_element = None
        stuck_count = 0

        yield self._progress("Checking for JS-only links and mouse-only handlers...")
        static_issues = await page.evaluate(KEYBOARD_STATIC_JS)
        static_failures = [i for i in static_issues if i.get("severity") in ("critical", "serious")]
        static_warnings = [i for i in static_issues if i.get("severity") in ("moderate", "minor")]

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
                    text: (el.innerText||el.value||el.getAttribute('aria-label')||'').trim().slice(0,80),
                    role: el.getAttribute('role')||'',
                    outlineWidth: style.outlineWidth,
                    outlineColor: style.outlineColor,
                    outlineStyle: style.outlineStyle,
                    boxShadow: style.boxShadow,
                    visible: rect.width>0 && rect.height>0,
                    x: rect.x, y: rect.y,
                }
            }""")

            element_key = str(focus_info)
            if element_key == prev_element:
                stuck_count += 1
            else:
                stuck_count = 0
            prev_element = element_key

            if stuck_count >= 3:
                screenshot = await self.analyzer.screenshot_to_image(page)
                sp  = self.analyzer.save_screenshot(screenshot, self.run_dir, f"keyboard_trap_{tab_num}")
                sb64 = self.analyzer.image_to_base64(screenshot)
                yield self._result(TestResult(
                    test_id=self.TEST_ID, test_name=self.TEST_NAME,
                    result="fail", wcag_criteria=["2.1.2"], severity="critical",
                    failure_reason="Keyboard trap: focus did not move after 3 consecutive Tab presses.",
                    recommendation="Ensure all custom widgets and modals allow Tab/Shift+Tab to exit.",
                    screenshot_path=sp, screenshot_b64=sb64,
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
                if focus_info.get("text") else f"<{focus_info['tag']}>"
            )
            steps.append({
                "tab": tab_num, "focus_info": focus_info,
                "analysis": {"result": "pass", "focused_element": el_desc, "has_focus_style": has_outline or has_shadow},
            })

            if tab_num > 5 and focus_info.get("y", 999) < 100:
                yield self._progress("Focus cycled back to top — done.")
                break

        summary = await self.analyzer.screenshot_to_image(page)
        summary_path = self.analyzer.save_screenshot(summary, self.run_dir, "keyboard_summary")
        summary_b64  = self.analyzer.image_to_base64(summary)

        # Visual layer: ask MolmoWeb if skip nav is visible
        yield self._progress("Running MolmoWeb visual analysis for skip navigation...")
        molmo_analysis = await self._molmo_analyze(summary, self.MOLMO_QUESTION)

        # ── Agent layer (skip-nav + interactive states) ───────────────────────
        # The agent runs a quick capability probe first — if MolmoWeb outputs
        # trajectory gibberish (numbered lists, coordinates without context),
        # agent calls are skipped entirely rather than burning 60s per call.
        agent_findings: list[str] = []
        _agent_capable = await self._probe_agent_capable(page)

        if not _agent_capable:
            yield self._progress("[AGENT] MolmoWeb action output uninterpretable — skipping agent layer.")
        else:
            # 1. Verify skip-nav link is functional
            skip_links_found = not any(
                i.get("criterion") == "2.4.1" for i in static_issues
            )
            if skip_links_found:
                yield self._progress("[AGENT] clicking skip-nav link to verify it works...")
                try:
                    _agent_progress_msgs: list[str] = []
                    agent = MolmoWebAgentLoop(self.analyzer, max_steps=3)
                    skip_result = await agent.run(
                        page,
                        "Find the 'Skip to main content' or 'Skip navigation' link near the "
                        "top of the page and click it. Then describe where focus landed — "
                        "did it skip past the navigation to the main content?",
                        progress_cb=_agent_progress_msgs.append,
                    )
                    for msg in _agent_progress_msgs:
                        yield self._progress(msg)
                    if skip_result.steps and not skip_result.completion_reason.startswith("could not"):
                        summary_line = (
                            f"Skip-nav agent ({len(skip_result.steps)} steps): "
                            + skip_result.action_summary
                        )
                        if skip_result.thoughts:
                            summary_line += f" | {skip_result.thoughts[-1]}"
                        agent_findings.append(summary_line)
                        last_thought = (skip_result.thoughts or [""])[-1].lower()
                        if any(w in last_thought for w in ("did not", "didn't", "no skip", "not move", "fail")):
                            static_warnings.append({
                                "criterion": "2.4.1", "severity": "minor",
                                "description": (
                                    "Skip navigation link found but may not move focus "
                                    f"correctly: {skip_result.thoughts[-1]}"
                                ),
                                "examples": [],
                            })
                except Exception as e:
                    agent_findings.append(f"Skip-nav agent error (non-fatal): {e}")

            # 2. Discover hamburger menus, dropdowns, accordion nav toggles
            yield self._progress("[AGENT] testing interactive navigation elements...")
            try:
                _agent2_msgs: list[str] = []
                agent2 = MolmoWebAgentLoop(self.analyzer, max_steps=5)
                interactive_result = await agent2.run(
                    page,
                    "Look for navigation elements that open on click or interaction: "
                    "hamburger menus, dropdown menus, accordion nav sections, or 'More' buttons. "
                    "If you find one, click it to open it. Then press Tab twice and describe "
                    "whether the newly-revealed links/items are keyboard-focusable.",
                    progress_cb=_agent2_msgs.append,
                )
                for msg in _agent2_msgs:
                    yield self._progress(msg)
                if interactive_result.steps and not interactive_result.completion_reason.startswith("could not"):
                    agent_findings.append(
                        f"Interactive nav agent ({len(interactive_result.steps)} steps): "
                        + interactive_result.action_summary
                    )
                    for thought in interactive_result.thoughts:
                        if any(w in thought.lower() for w in ("not focusable", "can't tab", "cannot tab", "keyboard trap", "no focus")):
                            static_failures.append({
                                "criterion": "2.1.1", "severity": "serious",
                                "description": (
                                    "Interactive navigation element opened by MolmoWeb agent "
                                    f"appears keyboard-inaccessible: {thought}"
                                ),
                                "examples": [],
                            })
                            break
            except Exception as e:
                agent_findings.append(f"Interactive nav agent error (non-fatal): {e}")

        if agent_findings:
            molmo_analysis = (molmo_analysis + "\n" if molmo_analysis else "") + " | ".join(agent_findings)

        all_failures = static_failures
        all_warnings = static_warnings

        if all_failures:
            failure_reason = "; ".join(i["description"] for i in all_failures[:3])
            examples = []
            for i in all_failures[:2]:
                examples.extend(i.get("examples", [])[:2])
            if examples:
                failure_reason += f" — e.g.: {'; '.join(examples[:3])}"
            wcag = list(dict.fromkeys(i["criterion"] for i in all_failures))
            result = TestResult(
                test_id=self.TEST_ID, test_name=self.TEST_NAME,
                result="fail", wcag_criteria=wcag, severity="serious",
                failure_reason=failure_reason,
                recommendation=(
                    "Replace javascript: hrefs with proper event handlers. "
                    "Add tabindex + role to custom clickable elements. "
                    "Add a skip navigation link as the first focusable element."
                ),
                screenshot_path=summary_path, screenshot_b64=summary_b64,
                molmo_analysis=molmo_analysis,
                details={"steps": steps, "static_failures": static_failures, "static_warnings": static_warnings},
            )
        elif all_warnings:
            result = TestResult(
                test_id=self.TEST_ID, test_name=self.TEST_NAME,
                result="warning", wcag_criteria=["2.4.1"], severity="minor",
                failure_reason="; ".join(i["description"] for i in all_warnings),
                recommendation=(
                    "Add a visible 'Skip to main content' link as the first focusable element."
                ),
                screenshot_path=summary_path, screenshot_b64=summary_b64,
                molmo_analysis=molmo_analysis,
                details={"steps": steps, "static_warnings": static_warnings},
            )
        else:
            result = TestResult(
                test_id=self.TEST_ID, test_name=self.TEST_NAME,
                result="pass", wcag_criteria=self.WCAG_CRITERIA, severity="minor",
                screenshot_path=summary_path, screenshot_b64=summary_b64,
                molmo_analysis=molmo_analysis,
                details={"steps": steps, "tabs_tested": len(steps)},
            )

        yield self._result(result)
