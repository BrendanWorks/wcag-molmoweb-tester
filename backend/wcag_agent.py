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
        model_name: str = "allenai/Molmo2-4B",
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
            model_name, trust_remote_code=True,
            padding_side="left",
        )

        self.model_dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        model_kwargs = {
            "dtype": self.model_dtype,
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
        # (transformers 5.x stopped passing cache_position but the Molmo2 model code
        # still does cache_position[0], which crashes with NoneType.
        # FIX: wrap the ORIGINAL method and synthesize a valid cache_position
        # so Molmo2's own image-embedding logic runs correctly.)
        _orig_prepare = self.model.prepare_inputs_for_generation

        def _patched_prepare(input_ids, past_key_values=None, cache_position=None, **kwargs):
            if cache_position is None:
                if past_key_values is None:
                    # Prefill step: positions 0 .. seq_len-1
                    cache_position = torch.arange(
                        input_ids.shape[1], device=input_ids.device
                    )
                else:
                    # Decode step: single position after the cached sequence
                    if hasattr(past_key_values, "get_seq_length"):
                        past_len = past_key_values.get_seq_length()
                    elif isinstance(past_key_values, (list, tuple)) and len(past_key_values) > 0:
                        past_len = past_key_values[0][0].shape[2]
                    else:
                        past_len = input_ids.shape[1]
                    cache_position = torch.tensor(
                        [past_len], device=input_ids.device
                    )
            return _orig_prepare(
                input_ids,
                past_key_values=past_key_values,
                cache_position=cache_position,
                **kwargs,
            )

        self.model.prepare_inputs_for_generation = _patched_prepare
        print("WCAG agent ready (with cache_position shim)")

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
            # Official Molmo2 API: text BEFORE image in content array.
            messages = [{"role": "user", "content": [
                {"type": "text", "text": prompt},
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
                    else v.to(self.device)
                    if isinstance(v, torch.Tensor)
                    else v)
                for k, v in inputs.items()
            }

            input_len = inputs["input_ids"].shape[1]
            print(f"[Molmo2] Input keys: {list(inputs.keys())}")
            for k, v in inputs.items():
                shape = v.shape if isinstance(v, torch.Tensor) else type(v)
                print(f"[Molmo2]   {k}: {shape}")
            print(f"[Molmo2] token 198 decodes to: {repr(self.processor.decode([198]))}")
            print(f"[Molmo2] Input: {input_len} tokens, prompt: {prompt[:80]}...")

            autocast_ctx = (
                torch.autocast("cuda", dtype=torch.bfloat16)
                if self.device == "cuda"
                else torch.no_grad()
            )
            with torch.inference_mode(), autocast_ctx:
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=512,
                    do_sample=True,
                    temperature=0.7,
                    top_p=0.8,
                )

            # Only decode the NEW tokens (skip the echoed prompt)
            out_len = outputs[0].shape[0]
            new_tokens = outputs[0][input_len:]
            print(f"[Molmo2] input_len={input_len}, out_len={out_len}, new_tokens={len(new_tokens)}")
            print(f"[Molmo2] First 20 token IDs: {new_tokens[:20].tolist()}")
            response_raw = self.processor.decode(new_tokens, skip_special_tokens=False).strip()
            response = self.processor.decode(new_tokens, skip_special_tokens=True).strip()
            print(f"[Molmo2] RAW (with special): {response_raw[:300]}")
            print(f"[Molmo2] CLEAN: {response[:300]}")

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
