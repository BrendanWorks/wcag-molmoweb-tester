"""
MolmoWeb-8B inference wrapper for visual WCAG analysis.

MolmoWeb (released April 2026, allenai/MolmoWeb-8B) is Molmo2 fine-tuned on
web navigation trajectories and 2.2M screenshot QA pairs. We use it in two modes:

  1. QA mode    — ask WCAG-specific questions about a screenshot
                  e.g. "Is there a visible skip navigation link?"
  2. Point mode — locate an element in pixel space (same as existing Molmo2Pointer)
                  output: <point x="X" y="Y">  (coords in [0,100] → converted to px)

Three mandatory Transformers 5.x compat patches (same as existing Molmo2-4B usage):
  1. ROPE       — add missing "default" key to ROPE_INIT_FUNCTIONS
  2. ProcessorMixin — make __init__ lenient about unknown kwargs
  3. cache_position — shim missing arg in prepare_inputs_for_generation

WARNING: Do not remove these patches. Removing any one breaks inference
silently (repetition loops) or loudly (AttributeError / IndexError).
"""

from __future__ import annotations

import asyncio
import json
import re
from io import BytesIO
import base64
from pathlib import Path
from typing import Optional

import torch
from PIL import Image
from transformers import (
    AutoModelForImageTextToText,
    AutoProcessor,
    LogitsProcessor,
    LogitsProcessorList,
)


# ── Newline suppressor (prevents "the the the" / newline-loop failures) ────────

class ConsecutiveNewlineSuppressor(LogitsProcessor):
    """
    Hard-bans newline token (ID 198) after MAX_CONSECUTIVE consecutive newlines.
    Must NOT use standard repetition_penalty — Molmo2 image-token IDs exceed
    vocab_size and cause a crash in the penalty kernel.
    """
    NEWLINE_ID = 198
    MAX_CONSECUTIVE = 2

    def __call__(
        self, input_ids: torch.LongTensor, scores: torch.FloatTensor
    ) -> torch.FloatTensor:
        consecutive = 0
        for tok in reversed(input_ids[0].tolist()):
            if tok == self.NEWLINE_ID:
                consecutive += 1
            else:
                break
        if consecutive >= self.MAX_CONSECUTIVE:
            scores[:, self.NEWLINE_ID] = -float("inf")
        return scores


# ── MolmoWeb-8B analyzer ──────────────────────────────────────────────────────

class MolmoWebAnalyzer:
    """
    Thin inference wrapper around allenai/MolmoWeb-8B.

    Exposes three async methods:
      analyze(screenshot, question)   → plain-text answer  (QA mode)
      point_to(screenshot, query)     → (x, y) px | None   (point mode)
      screenshot_to_image(page)       → PIL.Image           (util)

    Both modes run in a thread executor so they never block the event loop.
    Loaded in bfloat16 (~16 GB on CUDA). MolmoWeb and OLMo are never resident
    simultaneously — caller must free this object before loading OLMo.
    """

    MODEL_NAME = "allenai/MolmoWeb-8B"
    FALLBACK_MODEL = "allenai/MolmoWeb-4B"

    def __init__(
        self,
        model_name: str = MODEL_NAME,
        use_quantization: bool = False,  # unused; kept for call-site compat
    ):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[MolmoWebAnalyzer] Loading {model_name} on {self.device}...")

        # ── Compat patch 1: ROPE "default" key ───────────────────────────────
        from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS
        if "default" not in ROPE_INIT_FUNCTIONS:
            def _default_rope(config, device=None):
                inv_freq = 1.0 / (
                    config.rope_theta ** (
                        torch.arange(
                            0, config.head_dim, 2,
                            dtype=torch.float32, device=device,
                        ) / config.head_dim
                    )
                )
                return inv_freq, 1.0
            ROPE_INIT_FUNCTIONS["default"] = _default_rope

        # ── Compat patch 2: ProcessorMixin lenient __init__ ──────────────────
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
            "trust_remote_code": True,
            "dtype": self.model_dtype,
        }
        if self.device == "cuda":
            model_kwargs["device_map"] = "auto"

        self.model = AutoModelForImageTextToText.from_pretrained(
            model_name, **model_kwargs
        )
        if self.device == "cpu":
            self.model = self.model.to(self.device)
        self.model.eval()

        # ── Compat patch 3: cache_position shim ──────────────────────────────
        # Transformers 5.x no longer passes cache_position to
        # prepare_inputs_for_generation; Molmo2 does cache_position[0] → crash.
        _orig_prepare = self.model.prepare_inputs_for_generation
        def _patched_prepare(input_ids, past_key_values=None, cache_position=None, **kw):
            if cache_position is None:
                if past_key_values is None:
                    cache_position = torch.arange(
                        input_ids.shape[1], device=input_ids.device
                    )
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
                input_ids,
                past_key_values=past_key_values,
                cache_position=cache_position,
                **kw,
            )
        self.model.prepare_inputs_for_generation = _patched_prepare

        # ── Compat patch 4: bypass _validate_model_kwargs (Transformers 5.5.3) ─
        # Transformers 5.5.3 tightened _validate_model_kwargs() to flag any kwarg
        # not explicitly listed in the model's forward() signature. Molmo2 passes
        # vision inputs (pixel_values, image_token_pooling, image_grids,
        # image_num_crops, attention_mask) via **kwargs in its forward signature
        # rather than as explicit named params, so the validator incorrectly
        # raises ValueError("... not used by the model").
        # Without this patch, every model.generate() call fails silently (caught
        # by _analyze_sync's broad except) → MolmoWeb returns "" for everything.
        self.model._validate_model_kwargs = lambda model_kwargs: None

        print(f"[MolmoWebAnalyzer] Ready ({self.device})")

    # ── Public async API ──────────────────────────────────────────────────────

    async def analyze(self, screenshot: Image.Image, question: str) -> str:
        """
        Ask MolmoWeb-8B a free-form accessibility question about a screenshot.
        Returns plain-text answer (max ~150 tokens).

        Wraps the question in an accessibility-expert framing.
        Use analyze_raw() when you need the model to follow a custom prompt
        exactly (e.g. the agent loop's JSON action format).

        Example:
            answer = await analyzer.analyze(img, "Is there a skip nav link?")
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._analyze_sync, screenshot, question
        )

    async def analyze_raw(
        self, screenshot: Image.Image, prompt: str, max_new_tokens: int = 200
    ) -> str:
        """
        Run inference with prompt passed directly — no QA wrapper added.

        Used by MolmoWebAgentLoop so that action-format prompts ("output JSON
        with thought + action keys") are not clobbered by the accessibility
        expert framing that analyze() adds.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._run_inference, screenshot, prompt, max_new_tokens
        )

    async def point_to(
        self, screenshot: Image.Image, query: str
    ) -> Optional[tuple[float, float]]:
        """
        Ask MolmoWeb to point to an element. Returns (x, y) in pixel space or None.
        MolmoWeb uses [0, 100] normalized coords; we denormalize to pixels.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._point_sync, screenshot, query
        )

    # ── Sync inference (runs in thread) ──────────────────────────────────────

    def _run_inference(
        self, screenshot: Image.Image, prompt: str, max_new_tokens: int = 200
    ) -> str:
        """Core inference — shared by both QA and point modes."""
        # Free any cached allocations from previous calls before starting a
        # new forward pass — reduces fragmentation on the A10G 24 GB budget.
        if self.device == "cuda":
            torch.cuda.empty_cache()

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
        # CRITICAL: remove token_type_ids → causes "the the the" loop if present
        inputs.pop("token_type_ids", None)
        inputs = {
            k: (
                v.to(self.device, dtype=self.model_dtype)
                if isinstance(v, torch.Tensor) and v.is_floating_point()
                else v.to(self.device) if isinstance(v, torch.Tensor)
                else v
            )
            for k, v in inputs.items()
        }
        input_len = inputs["input_ids"].shape[1]

        with torch.inference_mode():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                no_repeat_ngram_size=3,
                logits_processor=LogitsProcessorList([ConsecutiveNewlineSuppressor()]),
            )

        new_tokens = outputs[0][input_len:]
        return self.processor.decode(new_tokens, skip_special_tokens=True).strip()

    def _analyze_sync(self, screenshot: Image.Image, question: str) -> str:
        prompt = (
            "You are a web accessibility expert reviewing a webpage screenshot.\n"
            f"Question: {question}\n"
            "Give a concise, factual answer based only on what you can see in the screenshot. "
            "If you cannot determine the answer from the screenshot alone, say so."
        )
        response = self._run_inference(screenshot, prompt, max_new_tokens=180)
        print(f"[MolmoWebAnalyzer] QA '{question[:50]}' → {response[:80]}")
        return response

    def _point_sync(
        self, screenshot: Image.Image, query: str
    ) -> Optional[tuple[float, float]]:
        prompt = f"Point to: {query}"
        response = self._run_inference(screenshot, prompt, max_new_tokens=80)
        print(f"[MolmoWebAnalyzer] point '{query[:40]}' → {response[:60]}")
        return _parse_point(response, screenshot.size)

    # ── Screenshot utilities (used by WCAG checks) ────────────────────────────

    @staticmethod
    async def screenshot_to_image(page) -> Image.Image:
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


# ── Coordinate parser ─────────────────────────────────────────────────────────

def _parse_point(
    response: str, img_size: tuple[int, int]
) -> Optional[tuple[float, float]]:
    """
    Parse MolmoWeb pointing output into pixel coordinates.

    MolmoWeb normalizes coordinates to [0, 100]. Two output formats:
      Format 1 (Molmo base): <point x="X" y="Y">
      Format 2 (MolmoWeb action JSON): {"action": "mouse_click(x, y)"}
    """
    w, h = img_size

    # Format 1: <point x="..." y="...">
    m = re.search(
        r'<point[^>]*\bx=["\']?([\d.]+)["\']?[^>]*\by=["\']?([\d.]+)["\']?',
        response,
        re.IGNORECASE,
    )
    if m:
        x, y = float(m.group(1)), float(m.group(2))
        # Molmo uses [0, 100] percent; convert to pixels
        if x <= 100 and y <= 100:
            x, y = x / 100 * w, y / 100 * h
        return x, y

    # Format 2a: {"coordinate": [x, y]}
    m2 = re.search(r'"coordinate"\s*:\s*\[\s*([\d.]+)\s*,\s*([\d.]+)\s*\]', response)
    if m2:
        x, y = float(m2.group(1)), float(m2.group(2))
        # MolmoWeb action coordinates are also [0, 100]
        if x <= 100 and y <= 100:
            x, y = x / 100 * w, y / 100 * h
        return x, y

    # Format 2b: mouse_click(x, y) inside JSON action string
    m3 = re.search(r'mouse_click\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)', response)
    if m3:
        x, y = float(m3.group(1)), float(m3.group(2))
        if x <= 100 and y <= 100:
            x, y = x / 100 * w, y / 100 * h
        return x, y

    return None
