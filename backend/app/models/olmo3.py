"""
OLMo 3 narrative generator.

Called once after all pages are scanned to produce a multi-page executive
summary. Same model (allenai/OLMo-3-7B-Instruct) and same generation
settings as the existing WCAGAgent, adapted for site-wide results.
"""

from __future__ import annotations

import asyncio
import json
import re

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


class OLMo3Narrator:
    MODEL_NAME = "allenai/OLMo-3-7B-Instruct"

    # All valid WCAG 2.1 success criteria — used to strip hallucinations
    _VALID_WCAG_21 = {
        "1.1.1", "1.2.1", "1.2.2", "1.2.3", "1.2.4", "1.2.5",
        "1.3.1", "1.3.2", "1.3.3", "1.3.4", "1.3.5",
        "1.4.1", "1.4.2", "1.4.3", "1.4.4", "1.4.5",
        "1.4.10", "1.4.11", "1.4.12", "1.4.13",
        "2.1.1", "2.1.2", "2.1.4",
        "2.2.1", "2.2.2", "2.3.1",
        "2.4.1", "2.4.2", "2.4.3", "2.4.4", "2.4.5", "2.4.6", "2.4.7",
        "2.5.1", "2.5.2", "2.5.3", "2.5.4",
        "3.1.1", "3.1.2", "3.2.1", "3.2.2", "3.2.3", "3.2.4",
        "3.3.1", "3.3.2", "3.3.3", "3.3.4",
        "4.1.1", "4.1.2", "4.1.3",
    }

    def __init__(self, model_name: str = MODEL_NAME, use_quantization: bool = True):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[OLMo3] Loading {model_name} on {self.device}...")

        self.tokenizer = AutoTokenizer.from_pretrained(model_name)

        model_kwargs: dict = {}
        if self.device == "cuda":
            model_kwargs["device_map"] = "auto"
            # 4-bit NF4 on CUDA: drops OLMo-3-7B from ~14 GB (bfloat16) to
            # ~3.5 GB, keeping total VRAM (MolmoWeb ~4 GB + OLMo ~3.5 GB)
            # well within the A10G 24 GB budget.
            from transformers import BitsAndBytesConfig
            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )
        else:
            model_kwargs["torch_dtype"] = torch.float32

        self.model = AutoModelForCausalLM.from_pretrained(model_name, **model_kwargs)
        if self.device == "cpu":
            self.model = self.model.to(self.device)
        self.model.eval()
        print("[OLMo3] Ready")

    async def generate_narrative(
        self,
        all_results: list[dict],
        site_url: str,
        pages_scanned: int,
    ) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._narrative_sync, all_results, site_url, pages_scanned
        )

    def _narrative_sync(
        self,
        all_results: list[dict],
        site_url: str,
        pages_scanned: int,
    ) -> str:
        try:
            n_passed   = sum(1 for r in all_results if r.get("result") == "pass")
            n_failed   = sum(1 for r in all_results if r.get("result") == "fail")
            n_warnings = sum(1 for r in all_results if r.get("result") == "warning")
            n_total    = len(all_results)

            # Constrain criteria to only those actually tested
            all_criteria = sorted({
                c
                for r in all_results
                for c in r.get("wcag_criteria", [])
            })

            # Top 5 failure reasons
            failures = [r for r in all_results if r.get("result") == "fail"]
            top_failures = [
                {
                    "test": r.get("test_name", ""),
                    "page": r.get("page_url", ""),
                    "issue": r.get("failure_reason", "")[:120],
                    "wcag": r.get("wcag_criteria", []),
                    "severity": r.get("severity", ""),
                }
                for r in failures[:5]
            ]

            prompt = (
                f"You are a professional web accessibility auditor.\n"
                f"Site audit: {site_url}\n"
                f"Pages scanned: {pages_scanned}\n"
                f"Results across all pages: {n_passed} passed, {n_failed} failed, "
                f"{n_warnings} warnings out of {n_total} tests total. "
                f"Use these exact numbers — do not change them.\n\n"
                f"Top failures:\n{json.dumps(top_failures, indent=2)}\n\n"
                f"WCAG criteria tested: {', '.join(all_criteria)}. "
                f"Do NOT reference any criterion number outside this list.\n\n"
                f"Write a single executive summary paragraph of 120-160 words. "
                f"Cover: overall compliance across {pages_scanned} page(s) using "
                f"the exact counts above; the most critical and widespread issues; "
                f"and the single highest-priority fix. Address the development team "
                f"directly. No headings, no bullet points, plain prose only."
            )

            messages = [{"role": "user", "content": prompt}]
            formatted = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self.tokenizer(formatted, return_tensors="pt").to(self.device)

            with torch.inference_mode():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=280,
                    do_sample=True,
                    temperature=0.7,
                    top_p=0.9,
                )

            new_tokens = outputs[0][inputs["input_ids"].shape[1]:]
            narrative = self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
            narrative = self._strip_hallucinated_criteria(narrative)
            print(f"[OLMo3] Narrative: {len(narrative)} chars")
            return narrative

        except Exception as e:
            print(f"[OLMo3] Narrative error: {e}")
            import traceback; traceback.print_exc()
            return ""

    def _strip_hallucinated_criteria(self, text: str) -> str:
        def _check(m: re.Match) -> str:
            return m.group(0) if m.group(0) in self._VALID_WCAG_21 else ""
        return re.sub(r'\b\d+\.\d+(?:\.\d+)?\b', _check, text)
