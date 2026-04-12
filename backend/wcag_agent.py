#!/usr/bin/env python3
"""
WCAG Testing Agent — two-model architecture

  WCAGAgent      allenai/Olmo-3-7B-Instruct
                 Text-only. Called once after all tests complete to
                 produce the executive summary narrative.

  Molmo2Pointer  allenai/Molmo2-4B
                 Vision-language model used exclusively for POINTING.
                 After a programmatic CSS check says "focus indicator
                 exists", Molmo2 visually confirms: "Point to the
                 element with keyboard focus."  If it cannot locate it,
                 the indicator is technically present but visually
                 insufficient — a class of failure DOM inspection alone
                 cannot catch.
"""

import asyncio
import json
import re
from io import BytesIO
from pathlib import Path
import base64
from typing import Optional

from playwright.async_api import Page
from PIL import Image
import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    AutoModelForImageTextToText,
    AutoProcessor,
    LogitsProcessor,
    LogitsProcessorList,
)


# ── Safe newline suppressor (prevents Molmo2 512-newline loop) ────────────────

class ConsecutiveNewlineSuppressor(LogitsProcessor):
    """
    Hard-bans newline token (ID 198) after MAX_CONSECUTIVE consecutive
    newlines.  Safe because it only writes to scores[:,198] — a known-
    good vocabulary index.  Standard repetition_penalty crashes because
    Molmo2 image-token IDs exceed vocab_size.
    """
    NEWLINE_ID = 198
    MAX_CONSECUTIVE = 2

    def __call__(self, input_ids: torch.LongTensor, scores: torch.FloatTensor) -> torch.FloatTensor:
        consecutive = 0
        for tok in reversed(input_ids[0].tolist()):
            if tok == self.NEWLINE_ID:
                consecutive += 1
            else:
                break
        if consecutive >= self.MAX_CONSECUTIVE:
            scores[:, self.NEWLINE_ID] = -float("inf")
        return scores


# ── Molmo2 visual pointer ─────────────────────────────────────────────────────

class Molmo2Pointer:
    """
    Thin wrapper around allenai/Molmo2-4B that exposes a single method:

        point_to(screenshot, query) -> (x, y) | None

    Molmo2's pointing capability is unique to AllenAI's model family —
    no general-purpose API provides open pixel-coordinate output.
    We use it to visually confirm what programmatic CSS inspection found.
    """

    MODEL_NAME = "allenai/Molmo2-4B"

    def __init__(self, model_name: str = MODEL_NAME, use_quantization: bool = False):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[Molmo2Pointer] Loading {model_name} on {self.device}...")

        # ── Transformers 5.x compat patches ──────────────────────────────────
        from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS
        if "default" not in ROPE_INIT_FUNCTIONS:
            def _default_rope(config, device=None):
                base = config.rope_theta
                dim = config.head_dim
                inv_freq = 1.0 / (
                    base ** (torch.arange(0, dim, 2, dtype=torch.float32, device=device) / dim)
                )
                return inv_freq, 1.0
            ROPE_INIT_FUNCTIONS["default"] = _default_rope

        import transformers.processing_utils as _pu
        _orig_pm_init = _pu.ProcessorMixin.__init__
        def _lenient_init(self_proc, *args, **kwargs):
            known = set(self_proc.get_attributes()) | {"chat_template", "audio_tokenizer"}
            extras = {k: v for k, v in kwargs.items() if k not in known}
            clean  = {k: v for k, v in kwargs.items() if k in known}
            for k, v in extras.items():
                setattr(self_proc, k, v)
            return _orig_pm_init(self_proc, *args, **clean)
        _pu.ProcessorMixin.__init__ = _lenient_init

        self.processor = AutoProcessor.from_pretrained(
            model_name, trust_remote_code=True, padding_side="left"
        )

        self.model_dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        model_kwargs: dict = {
            "dtype": self.model_dtype,
            "device_map": "auto" if self.device == "cuda" else None,
            "trust_remote_code": True,
        }
        # Always quantize on CUDA — Molmo2 shares VRAM with OLMo3-7B (~14GB).
        # 4-bit drops Molmo2 from ~8GB to ~2GB; pointing quality is unaffected.
        if self.device == "cuda":
            from transformers import BitsAndBytesConfig
            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )
            model_kwargs.pop("dtype", None)  # incompatible with quantization_config

        self.model = AutoModelForImageTextToText.from_pretrained(model_name, **model_kwargs)
        if self.device == "cpu":
            self.model = self.model.to(self.device)
        self.model.eval()

        # cache_position shim (removed in transformers 5.x)
        _orig_prepare = self.model.prepare_inputs_for_generation
        def _patched_prepare(input_ids, past_key_values=None, cache_position=None, **kwargs):
            if cache_position is None:
                if past_key_values is None:
                    cache_position = torch.arange(input_ids.shape[1], device=input_ids.device)
                else:
                    try:
                        past_len = past_key_values.get_seq_length()
                    except Exception:
                        past_len = (
                            past_key_values[0][0].shape[2]
                            if isinstance(past_key_values, (list, tuple)) and past_key_values
                            else input_ids.shape[1]
                        )
                    cache_position = torch.tensor([past_len], device=input_ids.device)
            return _orig_prepare(
                input_ids, past_key_values=past_key_values,
                cache_position=cache_position, **kwargs,
            )
        self.model.prepare_inputs_for_generation = _patched_prepare

        print("[Molmo2Pointer] Ready")

    async def point_to(
        self, screenshot: Image.Image, query: str
    ) -> Optional[tuple[float, float]]:
        """
        Ask Molmo2: 'Point to [query]'.
        Returns (x, y) pixel coordinates in screenshot space, or None.
        Runs in a thread to avoid blocking the event loop.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._point_sync, screenshot, query)

    def _point_sync(
        self, screenshot: Image.Image, query: str
    ) -> Optional[tuple[float, float]]:
        try:
            prompt = f"Point to: {query}"
            messages = [{"role": "user", "content": [
                {"type": "text",  "text": prompt},
                {"type": "image", "image": screenshot},
            ]}]
            inputs = self.processor.apply_chat_template(
                messages,
                tokenize=True,
                return_dict=True,
                add_generation_prompt=True,
                return_tensors="pt",
                padding=True,
            )
            inputs.pop("token_type_ids", None)
            inputs = {
                k: (v.to(self.device, dtype=self.model_dtype)
                    if isinstance(v, torch.Tensor) and v.is_floating_point()
                    else v.to(self.device) if isinstance(v, torch.Tensor)
                    else v)
                for k, v in inputs.items()
            }
            input_len = inputs["input_ids"].shape[1]

            with torch.inference_mode():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=80,
                    do_sample=False,          # Greedy — pointing is deterministic
                    logits_processor=LogitsProcessorList([ConsecutiveNewlineSuppressor()]),
                )

            new_tokens = outputs[0][input_len:]
            response = self.processor.decode(new_tokens, skip_special_tokens=True).strip()
            print(f"[Molmo2] point_to '{query[:40]}' → {response[:80]}")

            coords = self._parse_point(response, screenshot.size)
            return coords

        except Exception as e:
            print(f"[Molmo2] point_to error: {e}")
            return None

    @staticmethod
    def _parse_point(
        response: str, img_size: tuple[int, int]
    ) -> Optional[tuple[float, float]]:
        """
        Parse Molmo's pointing output into pixel coordinates.
        Handles two formats:
          <point x="X" y="Y"> — Molmo base (coords in 0-100 percent-of-image space)
          {"coordinate": [x, y]}  — MolmoWeb action format (absolute pixels)
        """
        w, h = img_size

        # Format 1: <point x="..." y="...">
        m = re.search(
            r'<point[^>]*\bx=["\']?([\d.]+)["\']?[^>]*\by=["\']?([\d.]+)["\']?',
            response, re.IGNORECASE,
        )
        if m:
            x, y = float(m.group(1)), float(m.group(2))
            # Molmo uses 0–100 range (percent); convert to pixels
            if x <= 100 and y <= 100:
                x, y = x / 100 * w, y / 100 * h
            return x, y

        # Format 2: {"coordinate": [x, y]} or {"action": "click", "coordinate": [...]}
        m2 = re.search(r'"coordinate"\s*:\s*\[\s*([\d.]+)\s*,\s*([\d.]+)\s*\]', response)
        if m2:
            return float(m2.group(1)), float(m2.group(2))

        return None


# ── OLMo3 narrative agent ─────────────────────────────────────────────────────

class WCAGAgent:
    MODEL_NAME = "allenai/Olmo-3-7B-Instruct"

    def __init__(self, model_name: str = MODEL_NAME, use_quantization: bool = False):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        print(f"[OLMo3] Loading {model_name} on {self.device}...")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)

        model_kwargs: dict = {
            "dtype": torch.bfloat16 if self.device == "cuda" else torch.float32,
            "device_map": "auto" if self.device == "cuda" else None,
        }
        if use_quantization and self.device == "cuda":
            from transformers import BitsAndBytesConfig
            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )

        self.model = AutoModelForCausalLM.from_pretrained(model_name, **model_kwargs)
        if self.device == "cpu":
            self.model = self.model.to(self.device)
        self.model.eval()
        print("[OLMo3] Ready")

    # All valid WCAG 2.1 success criteria. Used to strip hallucinated references
    # from OLMo output — the model sometimes invents criterion numbers (e.g. "2.8")
    # that do not exist in the spec.
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

    def _strip_hallucinated_criteria(self, text: str) -> str:
        """Remove any WCAG criterion number that isn't in the WCAG 2.1 spec."""
        def _check(m: re.Match) -> str:
            crit = m.group(0)
            return crit if crit in self._VALID_WCAG_21 else ""
        return re.sub(r'\b\d+\.\d+(?:\.\d+)?\b', _check, text)

    async def generate_narrative(self, results: list, url: str) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._narrative_sync, results, url)

    def _narrative_sync(self, results: list, url: str) -> str:
        try:
            findings = [
                {
                    "test": r.get("test_name"),
                    "result": r.get("result"),
                    "wcag_criteria": r.get("wcag_criteria", []),
                    "severity": r.get("severity", ""),
                    "issue": r.get("failure_reason", ""),
                    "recommendation": r.get("recommendation", ""),
                }
                for r in results
            ]
            n_total    = len(findings)
            n_passed   = sum(1 for f in findings if f["result"] == "pass")
            n_failed   = sum(1 for f in findings if f["result"] == "fail")
            n_warnings = sum(1 for f in findings if f["result"] == "warning")
            # Constrain OLMo to only cite criteria that actually appear in the findings
            all_criteria = sorted({
                c for f in findings for c in f.get("wcag_criteria", [])
            })

            prompt = (
                f"You are a professional web accessibility auditor.\n"
                f"Audit of: {url}\n"
                f"Results: {n_passed} passed, {n_failed} failed, {n_warnings} warnings "
                f"out of {n_total} tests. Use these exact numbers — do not change them.\n\n"
                f"Findings:\n{json.dumps(findings, indent=2)}\n\n"
                f"WCAG criteria tested: {', '.join(all_criteria)}. "
                f"Do NOT reference any criterion number outside this list.\n\n"
                f"Write a single executive summary paragraph of 100-150 words. "
                f"Cover: the overall result using the exact counts above, the most critical "
                f"issues found and why they matter, and the single most important fix. "
                f"Address the development team directly. No headings, no bullet points, plain prose only."
            )

            messages = [{"role": "user", "content": prompt}]
            formatted = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self.tokenizer(formatted, return_tensors="pt").to(self.device)

            with torch.inference_mode():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=250,
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

    # ── Screenshot utilities ──────────────────────────────────────────────────

    @staticmethod
    async def screenshot_to_image(page: Page) -> Image.Image:
        raw = await page.screenshot(full_page=False)
        return Image.open(BytesIO(raw))

    @staticmethod
    def image_to_base64(img: Image.Image) -> str:
        buf = BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    @staticmethod
    def save_screenshot(img: Image.Image, run_dir: Path, name: str) -> str:
        path = run_dir / f"{name}.png"
        img.save(path)
        return str(path)
