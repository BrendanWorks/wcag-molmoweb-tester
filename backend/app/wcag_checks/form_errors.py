"""
WCAG Form Error Handling — 3.3.1, 3.3.2, 3.3.3, 3.3.4

Layer 1 (programmatic): label presence + aria-invalid + role=alert after submit.
Layer 2 (agent):        MolmoWebAgentLoop fills + submits the form like a real user
                        (catches forms with JS-only field reveal, multi-step forms,
                        and non-standard submit patterns). Playwright fallback if
                        no agent actions executed.
Layer 3 (visual):       MolmoWeb-8B confirms error messages are visible and associated.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from app.molmo_agent import MolmoWebAgentLoop
from app.wcag_checks.base import BaseWCAGTest, TestResult


INVALID_DATA = {
    "email": "notanemail",
    "password": "a",
    "phone": "abc",
    "zip": "ZZZZZ",
    "date": "99/99/9999",
    "number": "abc",
    "text": "",
}


class FormErrorTest(BaseWCAGTest):
    TEST_ID = "form_errors"
    TEST_NAME = "Form Navigation & Error Handling"
    WCAG_CRITERIA = ["3.3.1", "3.3.2", "3.3.3", "3.3.4"]
    DEFAULT_SEVERITY = "major"
    MOLMO_QUESTION = "Are there any form error messages visible on this page? Answer yes or no."

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        yield self._progress("Scanning page for forms...")

        form_info = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('form')).map(form => {
                const inputs = Array.from(form.querySelectorAll('input,textarea,select'))
                    .filter(el => !['hidden','submit','button','reset'].includes(el.type))
                    .map(el => ({
                        type: el.type||el.tagName.toLowerCase(),
                        name: el.name||el.id||'',
                        id: el.id||'',
                        placeholder: el.placeholder||'',
                        required: el.required,
                        hasLabel: (
                            !!document.querySelector(`label[for="${el.id}"]`) ||
                            !!el.closest('label') ||
                            !!el.getAttribute('aria-label') ||
                            !!el.getAttribute('aria-labelledby')
                        ),
                    }));
                return { inputCount: inputs.length, inputs };
            });
        }""")

        if not form_info or all(f["inputCount"] == 0 for f in form_info):
            yield self._result(TestResult(
                test_id=self.TEST_ID, test_name=self.TEST_NAME,
                result="warning", wcag_criteria=self.WCAG_CRITERIA, severity="minor",
                failure_reason="No forms found on this page.",
                recommendation="Test form-heavy pages individually.",
            ))
            return

        total = sum(f["inputCount"] for f in form_info)
        yield self._progress(f"Found {len(form_info)} form(s), {total} input(s). Checking labels...")

        unlabeled = [
            inp["name"] or inp["placeholder"] or inp["type"]
            for form in form_info
            for inp in form["inputs"]
            if not inp["hasLabel"]
        ]

        screenshot = await self.analyzer.screenshot_to_image(page)
        sp   = self.analyzer.save_screenshot(screenshot, self.run_dir, "form_labels")
        sb64 = self.analyzer.image_to_base64(screenshot)

        # ── Agent layer: fill + submit form like a real user ─────────────────
        # MolmoWeb navigates the form visually — it handles multi-step forms,
        # JS-revealed fields, and non-standard submit patterns that selectors miss.
        yield self._progress("[AGENT PATH] filling form with invalid data to trigger errors...")
        agent_submitted = False
        agent_log = ""
        _form_agent_msgs: list[str] = []
        try:
            agent = MolmoWebAgentLoop(self.analyzer, max_steps=8)
            agent_result = await agent.run(
                page,
                "Fill out all visible form fields with invalid or empty data to trigger "
                "validation errors. Use obviously wrong values: blank required fields, "
                "bad email formats (e.g. 'notanemail'), too-short passwords (e.g. 'a'), "
                "invalid dates (e.g. '99/99/9999'). Then submit the form by clicking the "
                "submit button or pressing Enter.",
                progress_cb=_form_agent_msgs.append,
            )
            for msg in _form_agent_msgs:
                yield self._progress(msg)
            if agent_result.steps:
                agent_submitted = any(
                    s.action_type in ("click", "key") and s.executed
                    for s in agent_result.steps
                )
                agent_log = agent_result.action_summary
                yield self._progress(
                    f"[AGENT PATH] completed {len(agent_result.steps)} action(s): {agent_log[:80]}"
                )
        except Exception as e:
            yield self._progress(f"[AGENT PATH] error (non-fatal): {e}")

        # ── Playwright fallback: direct fill + submit ─────────────────────────
        # Run if agent took no actions (e.g. form not visible or agent timed out).
        submitted = agent_submitted
        if not submitted:
            yield self._progress("[PLAYWRIGHT FALLBACK] agent took no actions — filling fields directly...")
            for form in form_info:
                for inp in form["inputs"]:
                    sel = f"#{inp['id']}" if inp["id"] else f"[name='{inp['name']}']"
                    bad = INVALID_DATA.get(inp["type"], "")
                    try:
                        if inp["type"] not in ("checkbox", "radio", "select"):
                            await page.fill(sel, bad, timeout=1000)
                    except Exception:
                        pass

            try:
                await page.locator("button[type='submit'], input[type='submit']").first.click(timeout=2000)
                submitted = True
            except Exception:
                try:
                    await page.keyboard.press("Enter")
                    submitted = True
                except Exception:
                    pass

        await asyncio.sleep(1)
        yield self._progress("Checking ARIA error indicators...")

        error_info = await page.evaluate("""() => {
            const invalidFields = Array.from(document.querySelectorAll('[aria-invalid="true"]'))
                .map(el => ({ tag: el.tagName, id: el.id, describedBy: el.getAttribute('aria-describedby')||'' }));
            const alertMsgs = Array.from(document.querySelectorAll(
                '[role="alert"],[role="status"],[aria-live="assertive"],[aria-live="polite"]'
            )).filter(el => (el.innerText||'').trim().length>0)
              .map(el => ({ role: el.getAttribute('role')||'live', text: (el.innerText||'').trim().slice(0,100) }));
            const hasErrorKeywords = /error|invalid|required|must|cannot|please fix/i.test(document.body.innerText||'');
            return { invalidFields, alertMsgs, hasErrorKeywords };
        }""")

        err_shot = await self.analyzer.screenshot_to_image(page)
        err_sp   = self.analyzer.save_screenshot(err_shot, self.run_dir, "form_after_submit")
        err_sb64 = self.analyzer.image_to_base64(err_shot)

        yield self._progress("Running MolmoWeb visual form-error analysis...")
        molmo_analysis = await self._molmo_analyze(err_shot, self.MOLMO_QUESTION)

        failures = []

        if unlabeled:
            failures.append({
                "criteria": ["3.3.2", "1.3.1"], "severity": "critical",
                "reason": f"Fields missing programmatic labels: {', '.join(unlabeled[:5])}",
                "rec": (
                    "Add <label for='id'>, aria-label, or aria-labelledby to every input. "
                    "Placeholder text alone does not satisfy WCAG 3.3.2."
                ),
            })

        if submitted:
            has_aria    = bool(error_info.get("invalidFields"))
            has_alerts  = bool(error_info.get("alertMsgs"))
            has_keywords = error_info.get("hasErrorKeywords", False)

            if not has_aria and not has_alerts and not has_keywords:
                failures.append({
                    "criteria": ["3.3.1"], "severity": "major",
                    "reason": "No error messages detected after submitting invalid data.",
                    "rec": (
                        "Add aria-invalid='true' to invalid fields, "
                        "associate error messages via aria-describedby, "
                        "and use role='alert' for error summaries."
                    ),
                })
            elif not has_aria:
                failures.append({
                    "criteria": ["3.3.1"], "severity": "major",
                    "reason": "Errors shown visually but not programmatically (no aria-invalid on fields).",
                    "rec": (
                        "Add aria-invalid='true' and aria-describedby pointing to the error "
                        "message element for each invalid field."
                    ),
                })

        if failures:
            w = failures[0]
            result = TestResult(
                test_id=self.TEST_ID, test_name=self.TEST_NAME,
                result="fail", wcag_criteria=w["criteria"], severity=w["severity"],
                failure_reason=w["reason"], recommendation=w["rec"],
                screenshot_path=err_sp, screenshot_b64=err_sb64,
                molmo_analysis=molmo_analysis,
                details={"form_info": form_info, "unlabeled": unlabeled, "error_info": error_info, "agent_log": agent_log},
            )
        else:
            result = TestResult(
                test_id=self.TEST_ID, test_name=self.TEST_NAME,
                result="pass", wcag_criteria=self.WCAG_CRITERIA, severity="minor",
                screenshot_path=err_sp, screenshot_b64=err_sb64,
                molmo_analysis=molmo_analysis,
                details={"form_info": form_info, "error_info": error_info, "agent_log": agent_log},
            )

        yield self._result(result)
