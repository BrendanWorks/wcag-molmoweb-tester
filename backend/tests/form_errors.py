"""
WCAG 2.1 Form Error Handling Test
Maps to: 3.3.1 (Error Identification), 3.3.2 (Labels or Instructions),
         3.3.3 (Error Suggestion), 3.3.4 (Error Prevention)

Finds forms on the page, submits with intentionally bad data,
then checks if error messages are descriptive, associated with fields,
and provide suggestions for correction.
"""

import asyncio
from typing import AsyncGenerator

from tests.base_test import BaseWCAGTest, TestResult

LABEL_PROMPT = """You are a WCAG 2.1 Level AA accessibility auditor.

Look at this form carefully.

1. Does every input field have a visible label ABOVE or BESIDE it (not just placeholder text)?
2. Are required fields indicated by more than just color (e.g., asterisk + text saying "required")?
3. Are there any instructions for complex fields (password requirements, date format, etc.)?

Respond ONLY with this JSON (no other text):
{{
  "all_fields_labeled": true,
  "required_fields_indicated": true,
  "instructions_present": true,
  "unlabeled_fields": ["list any fields without proper labels"],
  "result": "pass|fail",
  "failure_reason": "if fail, describe (empty string if pass)",
  "wcag_criteria": ["3.3.2"],
  "severity": "critical|major|minor",
  "recommendation": "specific fix if failed (empty string if pass)"
}}"""

ERROR_PROMPT = """You are a WCAG 2.1 Level AA accessibility auditor.

A form was submitted with intentionally invalid data to test error handling.
Look at the screenshot.

1. Are error messages displayed?
2. Are error messages associated with specific fields (not just a generic top-of-page summary)?
3. Do the error messages describe WHAT went wrong (not just "Invalid input")?
4. Do they suggest HOW to fix the error?
5. Are error indicators visible beyond just color (icon, text "Error:", bold, etc.)?

Respond ONLY with this JSON (no other text):
{{
  "errors_displayed": true,
  "errors_associated_with_fields": true,
  "errors_descriptive": true,
  "suggestions_provided": true,
  "non_color_indicator": true,
  "result": "pass|fail",
  "failure_reason": "if fail, describe what is missing (empty string if pass)",
  "wcag_criteria": ["3.3.1", "3.3.3"],
  "severity": "critical|major|minor",
  "recommendation": "specific fix if failed (empty string if pass)"
}}"""

INVALID_DATA = {
    "email": "notanemail",
    "password": "a",
    "phone": "abc",
    "zip": "ZZZZZ",
    "date": "99/99/9999",
    "number": "abc",
    "text": "",  # Leave text fields empty to trigger required validation
}


class FormErrorTest(BaseWCAGTest):
    TEST_ID = "form_errors"
    TEST_NAME = "Form Navigation & Error Handling"
    WCAG_CRITERIA = ["3.3.1", "3.3.2", "3.3.3", "3.3.4"]
    DEFAULT_SEVERITY = "major"

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        yield self._progress("Scanning page for forms...")

        form_info = await page.evaluate("""() => {
            const forms = Array.from(document.querySelectorAll('form'));
            return forms.map(form => {
                const inputs = Array.from(form.querySelectorAll('input, textarea, select'))
                    .filter(el => !['hidden', 'submit', 'button', 'reset'].includes(el.type))
                    .map(el => ({
                        type: el.type || el.tagName.toLowerCase(),
                        name: el.name || el.id || '',
                        id: el.id || '',
                        placeholder: el.placeholder || '',
                        required: el.required,
                        hasLabel: !!document.querySelector(`label[for="${el.id}"]`) ||
                                  !!el.closest('label') ||
                                  !!el.getAttribute('aria-label') ||
                                  !!el.getAttribute('aria-labelledby'),
                    }));
                return { inputCount: inputs.length, inputs };
            });
        }""")

        if not form_info or all(f["inputCount"] == 0 for f in form_info):
            result = TestResult(
                test_id=self.TEST_ID,
                test_name=self.TEST_NAME,
                result="warning",
                wcag_criteria=self.WCAG_CRITERIA,
                severity="minor",
                failure_reason="No forms found on this page.",
                recommendation="If forms exist behind navigation, test those pages individually.",
            )
            yield self._result(result)
            return

        total_inputs = sum(f["inputCount"] for f in form_info)
        yield self._progress(
            f"Found {len(form_info)} form(s) with {total_inputs} input(s). Checking labels..."
        )

        screenshot = await self.agent.screenshot_to_image(page)
        screenshot_path = self.agent.save_screenshot(
            screenshot, self.run_dir, "form_labels"
        )
        screenshot_b64 = self.agent.image_to_base64(screenshot)
        label_analysis = await self.agent.analyze_screenshot(screenshot, LABEL_PROMPT)

        # DOM-level label check
        unlabeled = [
            inp["name"] or inp["placeholder"] or inp["type"]
            for form in form_info
            for inp in form["inputs"]
            if not inp["hasLabel"]
        ]
        if unlabeled:
            label_analysis["all_fields_labeled"] = False
            label_analysis["result"] = "fail"
            label_analysis["unlabeled_fields"] = unlabeled
            label_analysis["failure_reason"] = (
                f"Fields missing programmatic labels: {', '.join(unlabeled[:5])}"
            )
            label_analysis["wcag_criteria"] = ["3.3.2", "1.3.1"]
            label_analysis["severity"] = "critical"
            label_analysis["recommendation"] = (
                "Add <label for='fieldId'> elements or aria-label/aria-labelledby attributes "
                "to all inputs. Placeholder text alone does not satisfy WCAG 3.3.2."
            )

        yield self._progress("Filling form with invalid data to trigger error messages...")

        # Fill inputs with invalid data
        for form in form_info:
            for inp in form["inputs"]:
                input_type = inp["type"]
                selector = f"#{inp['id']}" if inp["id"] else f"[name='{inp['name']}']"
                bad_value = INVALID_DATA.get(input_type, "")
                try:
                    if input_type == "select":
                        # Select first non-default option or leave blank
                        pass
                    elif input_type in ("checkbox", "radio"):
                        pass
                    else:
                        await page.fill(selector, bad_value, timeout=1000)
                except Exception:
                    pass

        # Submit the first form
        submitted = False
        try:
            submit_btn = page.locator("button[type='submit'], input[type='submit']").first
            await submit_btn.click(timeout=2000)
            submitted = True
        except Exception:
            try:
                await page.keyboard.press("Enter")
                submitted = True
            except Exception:
                pass

        await asyncio.sleep(1)

        yield self._progress("Checking error messages...")
        error_screenshot = await self.agent.screenshot_to_image(page)
        error_screenshot_path = self.agent.save_screenshot(
            error_screenshot, self.run_dir, "form_errors"
        )
        error_screenshot_b64 = self.agent.image_to_base64(error_screenshot)
        error_analysis = await self.agent.analyze_screenshot(error_screenshot, ERROR_PROMPT)

        # Combine label + error results
        has_failure = (
            label_analysis.get("result") == "fail"
            or error_analysis.get("result") == "fail"
        )

        if has_failure:
            # Pick worst failure
            primary = (
                label_analysis if label_analysis.get("result") == "fail" else error_analysis
            )
            result = TestResult(
                test_id=self.TEST_ID,
                test_name=self.TEST_NAME,
                result="fail",
                wcag_criteria=primary.get("wcag_criteria", self.WCAG_CRITERIA),
                severity=primary.get("severity", self.DEFAULT_SEVERITY),
                failure_reason=primary.get("failure_reason", ""),
                recommendation=primary.get("recommendation", ""),
                screenshot_path=error_screenshot_path,
                screenshot_b64=error_screenshot_b64,
                details={
                    "label_analysis": label_analysis,
                    "error_analysis": error_analysis,
                    "form_info": form_info,
                    "submitted": submitted,
                    "unlabeled_fields": unlabeled,
                },
            )
        else:
            result = TestResult(
                test_id=self.TEST_ID,
                test_name=self.TEST_NAME,
                result="pass",
                wcag_criteria=self.WCAG_CRITERIA,
                severity="minor",
                screenshot_path=error_screenshot_path,
                screenshot_b64=error_screenshot_b64,
                details={
                    "label_analysis": label_analysis,
                    "error_analysis": error_analysis,
                    "form_info": form_info,
                },
            )

        yield self._result(result)
