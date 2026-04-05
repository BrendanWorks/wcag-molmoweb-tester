#!/usr/bin/env python3
"""
WCAG 2.1 Level AA Testing Agent
Adapted from game_testing_agent.py — uses MolmoWeb to visually analyze
accessibility constraints instead of game objectives.
"""

import asyncio
import json
import re
import base64
from io import BytesIO
from pathlib import Path
from datetime import datetime
from typing import Optional

from playwright.async_api import Page
from PIL import Image
import torch
from transformers import AutoModelForImageTextToText, AutoProcessor


class WCAGAgent:
    def __init__(
        self,
        model_name: str = "allenai/MolmoWeb-4B",
        use_quantization: bool = False,
    ):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        print(f"Initializing WCAG agent on {self.device}")
        print(f"Loading {model_name}...")

        # ── Compat patches for transformers 5.x ──────────────────────
        # 1) ROPE_INIT_FUNCTIONS is missing 'default' key in transformers 5.x
        from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS
        if "default" not in ROPE_INIT_FUNCTIONS:
            import torch as _torch

            def _default_rope(config, device=None):
                base = config.rope_theta
                dim = config.head_dim
                inv_freq = 1.0 / (base ** (_torch.arange(0, dim, 2, dtype=_torch.float32, device=device) / dim))
                return inv_freq, 1.0  # (inv_freq, attention_scaling=1.0)

            ROPE_INIT_FUNCTIONS["default"] = _default_rope

        # 2) ProcessorMixin.__init__ rejects unknown kwargs from MolmoWeb's
        # remote code (image_use_col_tokens, use_single_crop_col_tokens, etc.)
        import transformers.processing_utils as _pu
        _orig_pm_init = _pu.ProcessorMixin.__init__

        def _lenient_init(self_proc, *args, **kwargs):
            known = set(self_proc.get_attributes()) | {"chat_template", "audio_tokenizer"}
            extras = {k: v for k, v in kwargs.items() if k not in known}
            clean = {k: v for k, v in kwargs.items() if k in known}
            for k, v in extras.items():
                setattr(self_proc, k, v)
            return _orig_pm_init(self_proc, *args, **clean)

        _pu.ProcessorMixin.__init__ = _lenient_init

        self.processor = AutoProcessor.from_pretrained(
            model_name, trust_remote_code=True
        )

        model_kwargs = {
            "torch_dtype": torch.bfloat16 if self.device == "cuda" else torch.float32,
            "device_map": "auto" if self.device == "cuda" else None,
            "trust_remote_code": True,
        }

        if use_quantization and self.device == "cuda":
            from transformers import BitsAndBytesConfig

            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )

        self.model = AutoModelForImageTextToText.from_pretrained(model_name, **model_kwargs)
        if self.device == "cpu":
            self.model = self.model.to(self.device)
        self.model.eval()

        # Monkey-patch prepare_inputs_for_generation to handle cache_position=None
        # (transformers 5.x removed cache_position but the model code still expects it)
        _orig_prepare = self.model.prepare_inputs_for_generation

        def _patched_prepare(input_ids, past_key_values=None, cache_position=None, **kwargs):
            # Determine if this is the prefill (first) step
            is_prefill = (
                (cache_position is not None and cache_position[0] == 0)
                or (cache_position is None and past_key_values is None)
            )

            # Extract image kwargs before calling parent
            pixel_values = kwargs.pop("pixel_values", None)
            image_token_pooling = kwargs.pop("image_token_pooling", None)
            image_grids = kwargs.pop("image_grids", None)
            image_num_crops = kwargs.pop("image_num_crops", None)
            pixel_values_videos = kwargs.pop("pixel_values_videos", None)
            video_token_pooling = kwargs.pop("video_token_pooling", None)
            video_grids = kwargs.pop("video_grids", None)

            # Call grandparent's prepare_inputs (skip the broken override)
            from transformers import GenerationMixin
            model_inputs = GenerationMixin.prepare_inputs_for_generation(
                self.model, input_ids,
                past_key_values=past_key_values,
                cache_position=cache_position,
                **kwargs,
            )

            # Only pass image data on the first (prefill) step
            if is_prefill:
                model_inputs["pixel_values"] = pixel_values
                model_inputs["image_token_pooling"] = image_token_pooling
                model_inputs["image_grids"] = image_grids
                model_inputs["image_num_crops"] = image_num_crops
                model_inputs["pixel_values_videos"] = pixel_values_videos
                model_inputs["video_token_pooling"] = video_token_pooling
                model_inputs["video_grids"] = video_grids

            return model_inputs

        self.model.prepare_inputs_for_generation = _patched_prepare
        print("WCAG agent ready (with cache_position patch)")

    async def analyze_screenshot(
        self, screenshot: Image.Image, prompt: str
    ) -> dict:
        """
        Send a screenshot + accessibility prompt to MolmoWeb.
        Returns parsed JSON dict from the model.
        Runs inference in a thread to avoid blocking the async event loop.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._analyze_sync, screenshot, prompt)

    def _analyze_sync(self, screenshot: Image.Image, prompt: str) -> dict:
        """Synchronous inference — called from a thread."""
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image"},
                        {"type": "text", "text": prompt},
                    ],
                }
            ]

            text_input = self.processor.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=False
            )

            inputs = self.processor(
                images=[screenshot],
                text=text_input,
                return_tensors="pt",
                padding=True,
            )
            inputs = {
                k: v.to(self.device) if isinstance(v, torch.Tensor) else v
                for k, v in inputs.items()
            }

            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=512,
                    temperature=0.3,
                    top_p=0.9,
                )

            response = self.processor.decode(outputs[0], skip_special_tokens=True)
            print(f"[MolmoWeb] Raw response: {response[:200]}...")

            # Strip the echoed prompt (MolmoWeb repeats the input)
            if "<|assistant|>" in response:
                response = response.split("<|assistant|>")[-1].strip()

            try:
                json_match = re.search(r"\{.*\}", response, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except (json.JSONDecodeError, AttributeError):
                pass

            # Fallback — return raw model text as analysis note
            return {
                "result": "error",
                "failure_reason": "Model did not return valid JSON",
                "raw_response": response[:500],
                "severity": "minor",
                "recommendation": "Re-run test or inspect manually",
            }
        except Exception as e:
            print(f"[MolmoWeb] Inference error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "result": "error",
                "failure_reason": f"Model inference error: {str(e)}",
                "severity": "minor",
                "recommendation": "Check model compatibility and retry",
            }

    @staticmethod
    async def screenshot_to_image(page: Page) -> Image.Image:
        """Capture current page as PIL Image."""
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
