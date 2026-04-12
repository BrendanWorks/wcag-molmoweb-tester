"""
WCAG Resize Text & Reflow — 1.4.4, 1.4.10

Layer 1 (programmatic): CDP 200% zoom + DOM scroll/clip inspection.
Layer 2 (visual): MolmoWeb-8B confirms horizontal overflow visually.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from app.wcag_checks.base import BaseWCAGTest, TestResult


class ZoomTest(BaseWCAGTest):
    TEST_ID = "zoom"
    TEST_NAME = "Resize Text & Reflow"
    WCAG_CRITERIA = ["1.4.4", "1.4.10"]
    DEFAULT_SEVERITY = "major"
    MOLMO_QUESTION = "Does any content extend past the right edge of the screen? Answer yes or no."

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        yield self._progress("Capturing baseline screenshot...")
        baseline = await self.analyzer.screenshot_to_image(page)
        self.analyzer.save_screenshot(baseline, self.run_dir, "zoom_baseline")

        yield self._progress("Applying 200% zoom via CDP...")
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 2})
        await asyncio.sleep(0.5)

        yield self._progress("Running programmatic reflow checks...")
        findings = await page.evaluate("""() => {
            const docEl = document.documentElement;
            const hasHorizontalScroll = docEl.scrollWidth > docEl.clientWidth + 5;

            const textEls = Array.from(document.querySelectorAll(
                'p, h1, h2, h3, h4, h5, h6, li, td, th, span, a, button, label'
            ));
            const clipped = textEls.filter(el => {
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                const offScreen   = r.left < -200 || r.top < -200;
                const tinyOrHidden = (r.width < 2 && r.height < 2) ||
                                     s.visibility === 'hidden' || s.display === 'none';
                const isSkipLink  = el.tagName === 'A' &&
                    ((el.getAttribute('href')||'').startsWith('#')) && offScreen;
                return (
                    !offScreen && !tinyOrHidden && !isSkipLink &&
                    r.width > 0 && r.height > 0 &&
                    (s.overflow === 'hidden' || s.textOverflow === 'ellipsis') &&
                    el.scrollWidth > el.clientWidth + 2
                );
            }).map(el => ({
                tag: el.tagName,
                text: (el.innerText||'').trim().slice(0,60),
            })).slice(0,5);

            return {
                scrollWidth: docEl.scrollWidth,
                clientWidth: docEl.clientWidth,
                hasHorizontalScroll,
                clippedElements: clipped,
            };
        }""")

        yield self._progress("Taking 200% zoom screenshot...")
        zoomed = await self.analyzer.screenshot_to_image(page)
        screenshot_path = self.analyzer.save_screenshot(zoomed, self.run_dir, "zoom_200pct")
        screenshot_b64  = self.analyzer.image_to_base64(zoomed)

        await cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 1})

        yield self._progress("Running MolmoWeb visual reflow analysis...")
        molmo_analysis = await self._molmo_analyze(zoomed, self.MOLMO_QUESTION)

        has_scroll = findings.get("hasHorizontalScroll", False)
        clipped    = findings.get("clippedElements", [])
        failures   = []

        if has_scroll:
            failures.append(
                f"Horizontal scrolling required at 200% zoom "
                f"(scrollWidth={findings['scrollWidth']}px vs clientWidth={findings['clientWidth']}px). "
                "Content must reflow to a single column (WCAG 1.4.10)."
            )
        if clipped:
            els = ", ".join(f"<{e['tag']}> '{e['text']}'" for e in clipped[:3])
            failures.append(f"Text clipped at 200% zoom: {els}")

        # Escalate to fail if MolmoWeb also sees horizontal overflow
        molmo_sees_overflow = molmo_analysis and any(
            kw in molmo_analysis.lower()
            for kw in ("horizontal scroll", "extends beyond", "overflow", "truncated", "yes")
        )
        if not failures and molmo_sees_overflow:
            failures.append(
                f"MolmoWeb visual analysis detected possible horizontal overflow at zoom. "
                f"Details: {molmo_analysis[:120]}"
            )

        if failures:
            result = TestResult(
                test_id=self.TEST_ID,
                test_name="Resize Text & Reflow" if (has_scroll and clipped) else
                          ("Reflow (1.4.10)" if has_scroll else "Resize Text (1.4.4)"),
                result="fail",
                wcag_criteria=["1.4.10"] if has_scroll else ["1.4.4"],
                severity="major",
                failure_reason=" | ".join(failures),
                recommendation=(
                    "Use responsive CSS (flexbox/grid, max-width, relative units). "
                    "Avoid fixed-width containers. Test at 320px viewport width. "
                    "Remove overflow:hidden from text containers."
                ),
                screenshot_path=screenshot_path, screenshot_b64=screenshot_b64,
                molmo_analysis=molmo_analysis, details=findings,
            )
        else:
            result = TestResult(
                test_id=self.TEST_ID, test_name=self.TEST_NAME,
                result="pass", wcag_criteria=self.WCAG_CRITERIA, severity="minor",
                screenshot_path=screenshot_path, screenshot_b64=screenshot_b64,
                molmo_analysis=molmo_analysis, details=findings,
            )

        yield self._result(result)
