"""
MolmoWeb-8B inference wrapper for visual WCAG analysis.

MolmoWeb (released April 2026, allenai/MolmoWeb-8B) is Molmo2 fine-tuned on
web navigation trajectories and 2.2M screenshot QA pairs. We use it in two modes:

  1. QA mode    — ask WCAG-specific questions about a screenshot
                  e.g. "Where is the skip navigation link?"
  2. Point mode — locate an element in pixel space
                  output: <point x="X" y="Y">  (coords in [0,100] → converted to px)

Four mandatory Transformers 5.x compat patches:
  1. ROPE       — add missing "default" key to ROPE_INIT_FUNCTIONS
  2. ProcessorMixin — make __init__ lenient about unknown kwargs
  3. cache_position — shim missing arg in prepare_inputs_for_generation
  4. _validate_model_kwargs — bypass overly-strict kwarg validator (Transformers 5.5.3)

DEVICE INVARIANT: After from_pretrained, we explicitly call .to("cuda") to ensure
every parameter — including MolmoWeb's new_embedding (added post-init for action
tokens) — is on CUDA. device_map={"": 0} alone is not sufficient because new_embedding
is registered after the standard loading path and defaults to CPU.

WARNING: Do not remove these patches. Removing any one breaks inference
silently (repetition loops) or loudly (AttributeError / IndexError).
"""

from __future__ import annotations

import asyncio
import gc
import re
from io import BytesIO
import base64
from pathlib import Path
from typing import Optional

import torch
from PIL import Image
from transformers import (
    AutoModelForCausalLM,
    AutoModelForImageTextToText,
    AutoProcessor,
    BitsAndBytesConfig,
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


# ── Agent-format QA prompt ────────────────────────────────────────────────────
# MolmoWeb-8B was fine-tuned on web-navigation trajectories, not screenshot QA
# pairs. QA-format prompts (even with few-shot examples) cause trajectory-mode
# regression (numbered steps, mouse_click(), coordinate strings).
# The native agent format (Task / Previous actions / Action:) keeps the model
# on-distribution. We ask the WCAG question as the Task and extract the answer
# from the thought field or done() argument in the model's JSON output.

# ── Molmo-7B-D QA analyzer ────────────────────────────────────────────────────

class MolmoQAAnalyzer:
    """
    allenai/Molmo-7B-D-0924 in 4-bit NF4 for visual WCAG QA.

    MolmoWeb-8B is a web navigation model — it outputs action JSON
    (mouse_click, done, coordinates) rather than natural-language descriptions,
    making it unsuitable for screenshot QA tasks.

    Molmo-7B-D is the base Molmo model trained on image-text pairs. It outputs
    natural-language descriptions of what it sees, which is exactly what WCAG
    checks need.  Loaded in 4-bit NF4 (~4 GB VRAM) so it is co-resident with
    MolmoWeb-8B (~16 GB) on the same A10G GPU (24 GB total, ~20 GB used).
    """

    MODEL_NAME = "allenai/Molmo-7B-D-0924"

    def __init__(self, device: str = "cuda"):
        self.device = device
        print(f"[MolmoQAAnalyzer] Loading {self.MODEL_NAME} (4-bit NF4) on {device}...")

        # ── Compat patches for Molmo-7B-D-0924 on Transformers 5.x ─────────────
        import inspect as _inspect
        import transformers as _tf

        # Patch 1: all_tied_weights_keys — Transformers 5.x calls .keys() on
        # this in get_total_byte_count; must return a dict, not a list.
        if not hasattr(_tf.PreTrainedModel, "all_tied_weights_keys"):
            _tf.PreTrainedModel.all_tied_weights_keys = property(lambda self: {})

        self.processor = AutoProcessor.from_pretrained(
            self.MODEL_NAME, trust_remote_code=True, padding_side="left"
        )

        # Patch 2: tie_weights(missing_keys=...) — Transformers 5.x now passes
        # missing_keys to tie_weights(); Molmo's remote code defines it as
        # tie_weights(self) with no extra args.  Patching PreTrainedModel doesn't
        # help because Python's MRO finds the Molmo class first.  Instead, scan
        # sys.modules for every class the remote code registered and patch any
        # tie_weights that lacks missing_keys directly on that class.
        import sys as _sys
        def _make_safe_tie(orig_fn):
            def _safe(self, missing_keys=None, **kw):
                return orig_fn(self, **kw)
            return _safe
        _patched_count = 0
        for _mod in list(_sys.modules.values()):
            if _mod is None:
                continue
            _mod_name = getattr(_mod, "__name__", "") or ""
            if "molmo" not in _mod_name.lower():
                continue
            for _attr in list(vars(_mod).keys()):
                _cls = getattr(_mod, _attr, None)
                if not isinstance(_cls, type):
                    continue
                _own_tie = _cls.__dict__.get("tie_weights")
                if _own_tie is None:
                    continue
                _sig = _inspect.signature(_own_tie)
                if "missing_keys" not in _sig.parameters and "kwargs" not in _sig.parameters:
                    _cls.tie_weights = _make_safe_tie(_own_tie)
                    _patched_count += 1
        if _patched_count:
            print(f"[MolmoQAAnalyzer] tie_weights patch applied to {_patched_count} class(es)")

        model_kwargs: dict = {"trust_remote_code": True}
        if device == "cuda":
            if torch.cuda.is_available():
                free, total = torch.cuda.mem_get_info(0)
                print(
                    f"[MolmoQAAnalyzer] VRAM before load: "
                    f"{free/1e9:.1f} GB free / {total/1e9:.1f} GB total"
                )
            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )
            model_kwargs["device_map"] = {"": 0}
        else:
            model_kwargs["dtype"] = torch.float32

        self.model = AutoModelForCausalLM.from_pretrained(self.MODEL_NAME, **model_kwargs)

        # Bypass strict kwarg validator (same issue as MolmoWeb on Transformers 5.5.3)
        self.model._validate_model_kwargs = lambda model_kwargs: None
        self.model.eval()

        if device == "cuda" and torch.cuda.is_available():
            free2, total = torch.cuda.mem_get_info(0)
            print(
                f"[MolmoQAAnalyzer] VRAM after load: "
                f"{free2/1e9:.1f} GB free / {total/1e9:.1f} GB total"
            )

        print(f"[MolmoQAAnalyzer] Ready ({device})")

    def query(self, screenshot: Image.Image, question: str) -> str:
        """Ask a visual accessibility question. Returns a plain-text answer."""
        try:
            if self.device == "cuda":
                gc.collect()
                torch.cuda.empty_cache()

            # Cap width to avoid token overflow (same limit as MolmoWeb)
            if screenshot.width > 896:
                scale = 896 / screenshot.width
                screenshot = screenshot.resize(
                    (896, max(1, int(screenshot.height * scale))), Image.LANCZOS
                )

            prompt = (
                f"Answer this accessibility question about the webpage screenshot "
                f"in 1-2 clear sentences. Describe only what you can see.\n\n"
                f"Question: {question}"
            )

            raw = self.processor.process(images=screenshot, text=prompt)
            inputs = {
                k: (v.unsqueeze(0).to(self.device) if isinstance(v, torch.Tensor) else v)
                for k, v in raw.items()
            }

            input_len = inputs["input_ids"].shape[1]

            with torch.inference_mode():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=120,
                    do_sample=False,
                    no_repeat_ngram_size=3,
                    logits_processor=LogitsProcessorList([ConsecutiveNewlineSuppressor()]),
                )

            new_tokens = outputs[0][input_len:]
            return self.processor.decode(new_tokens, skip_special_tokens=True).strip()

        except Exception as e:
            print(f"[MolmoQAAnalyzer] query error: {e}")
            return ""


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

        if self.device == "cuda":
            # Flush any leftover allocations before loading (warm container safety).
            gc.collect()
            torch.cuda.empty_cache()
            free, total = torch.cuda.mem_get_info(0)
            print(
                f"[MolmoWebAnalyzer] VRAM before load: "
                f"{free/1e9:.1f} GB free / {total/1e9:.1f} GB total"
            )

        model_kwargs: dict = {
            "trust_remote_code": True,
            "dtype": self.model_dtype,
        }
        if self.device == "cuda":
            # Force ALL layers to GPU 0.  device_map="auto" on a warm container
            # sees fragmented VRAM and silently offloads layers to CPU, causing
            # "tensors on different devices" RuntimeError and garbage output.
            # Use "cuda" (not integer 0) so device strings match self.device —
            # using {"": 0} places params as "cuda:0" which then mismatches the
            # subsequent .to("cuda") call and triggers per-param move warnings
            # from MolmoWeb's trust_remote_code hooks.
            model_kwargs["device_map"] = {"": 0}

        self.model = AutoModelForImageTextToText.from_pretrained(
            model_name, **model_kwargs
        )

        # CRITICAL: move new_embedding to GPU after from_pretrained.
        # MolmoWeb adds `new_embedding` (action-token embeddings) after the
        # standard loading path — it registers to CPU even when device_map
        # places the rest of the model on GPU.
        # Do NOT call self.model.to(device) on the whole model — device_map
        # places all params as "cuda:0", and .to("cuda") triggers a per-param
        # device-string mismatch warning from the model's trust_remote_code
        # hooks for every single parameter, flooding the logs.
        if hasattr(self.model, "new_embedding"):
            self.model.new_embedding = self.model.new_embedding.to(self.device)
        self.model.eval()

        if self.device == "cuda":
            free2, _ = torch.cuda.mem_get_info(0)
            print(
                f"[MolmoWebAnalyzer] VRAM after load: "
                f"{free2/1e9:.1f} GB free / {total/1e9:.1f} GB total"
            )

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
        self.model._validate_model_kwargs = lambda model_kwargs: None

        print(f"[MolmoWebAnalyzer] Ready ({self.device})")

        # ── QA model (Molmo-7B-D) ─────────────────────────────────────────────
        # MolmoWeb-8B is a navigation model that outputs action JSON, not
        # natural-language descriptions. Molmo-7B-D-0924 (the base Molmo) is
        # loaded in 4-bit NF4 (~4 GB) alongside MolmoWeb-8B (~16 GB) to handle
        # all screenshot QA tasks. Total VRAM: ~20 GB on A10G (24 GB).
        self.qa_analyzer = MolmoQAAnalyzer(device=self.device)

    # ── Device helpers ────────────────────────────────────────────────────────

    def _ensure_cuda(self, tensor: torch.Tensor) -> torch.Tensor:
        """Move tensor to the model's device and correct dtype if needed."""
        if tensor.is_floating_point():
            return tensor.to(self.device, dtype=self.model_dtype)
        return tensor.to(self.device)

    # ── Public async API ──────────────────────────────────────────────────────

    async def analyze(self, screenshot: Image.Image, question: str) -> str:
        """
        Ask a free-form accessibility question about a screenshot.
        Returns plain-text answer (max ~120 tokens).

        Delegates to MolmoQAAnalyzer (Molmo-7B-D-0924 in 4-bit NF4), which is
        trained for visual description. MolmoWeb-8B is reserved for pointing
        and agent navigation — it outputs action JSON, not descriptions.
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

        Used by MolmoWebAgentLoop so that action-format prompts are not
        clobbered by the QA framing that analyze() adds.
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

    # Maximum screenshot width before passing to MolmoWeb.
    # 1280×720 → 7 crops × 729 tokens = 5,103 image tokens — exceeds MolmoWeb's
    # 4,096-token context window before any text is added.  Capping at 896px
    # gives 4–5 crops × 729 ≈ 3,600 image tokens, leaving room for the prompt.
    _MAX_IMG_WIDTH = 896

    def _run_inference(
        self,
        screenshot: Image.Image,
        prompt: str,
        max_new_tokens: int = 200,
        do_sample: bool = False,
        temperature: float = 1.0,
    ) -> str:
        """Core inference — shared by QA, point, and raw agent modes."""
        try:
            if self.device == "cuda":
                gc.collect()
                torch.cuda.empty_cache()

            # ── Resize screenshot to stay within MolmoWeb's context window ────
            # Each 448×448 crop costs 729 image tokens.  A 1280×720 viewport
            # creates 6+ crops → 4,374+ tokens, exceeding the 4,096 limit and
            # raising "Prompt is too long" before any text is tokenised.
            if screenshot.width > self._MAX_IMG_WIDTH:
                scale = self._MAX_IMG_WIDTH / screenshot.width
                new_h = max(1, int(screenshot.height * scale))
                screenshot = screenshot.resize(
                    (self._MAX_IMG_WIDTH, new_h), Image.LANCZOS
                )

            # ── Processor call ────────────────────────────────────────────────
            # MolmoWeb uses a native process() API (trust_remote_code=True).
            # process(images, text) inserts the <image> token and returns
            # unbatched tensors {input_ids, images, image_input_idx, ...}.
            # The standard HF processor(text=[...], images=[...]) call triggers
            # "Kwargs passed to processor.__call__ have to be in processor_kwargs"
            # because MolmoWeb's custom __call__ doesn't accept a top-level
            # `images` kwarg — the image patches never reach the vision encoder.
            inputs: dict
            try:
                raw = self.processor.process(images=screenshot, text=prompt)
                # process() returns unbatched tensors — add batch dimension
                inputs = {
                    k: self._ensure_cuda(v.unsqueeze(0)) if isinstance(v, torch.Tensor) else v
                    for k, v in raw.items()
                }
            except AttributeError:
                # Fallback for processor builds that don't have process():
                # two-step format-then-tokenize so the image goes through
                # the processor's own __call__ path.
                messages = [{"role": "user", "content": [
                    {"type": "image"},
                    {"type": "text", "text": prompt},
                ]}]
                try:
                    text = self.processor.apply_chat_template(
                        messages, tokenize=False, add_generation_prompt=True,
                    )
                except Exception:
                    text = prompt
                inputs = self.processor(
                    text=[text], images=[screenshot], return_tensors="pt", padding=True,
                )
                inputs.pop("token_type_ids", None)
                inputs = {
                    k: self._ensure_cuda(v) if isinstance(v, torch.Tensor) else v
                    for k, v in inputs.items()
                }

            input_len = inputs["input_ids"].shape[1]

            gen_kwargs: dict = dict(
                max_new_tokens=max_new_tokens,
                do_sample=do_sample,
                no_repeat_ngram_size=3,
                logits_processor=LogitsProcessorList([ConsecutiveNewlineSuppressor()]),
            )
            if do_sample:
                gen_kwargs["temperature"] = temperature
                gen_kwargs["top_p"] = 0.9

            with torch.inference_mode():
                outputs = self.model.generate(**inputs, **gen_kwargs)

            new_tokens = outputs[0][input_len:]
            return self.processor.decode(new_tokens, skip_special_tokens=True).strip()

        except Exception as e:
            print(f"[MolmoWebAnalyzer] _run_inference error: {e}")
            return ""

    def _analyze_sync(self, screenshot: Image.Image, question: str) -> str:
        answer = self.qa_analyzer.query(screenshot, question)
        print(f"[MolmoWebAnalyzer] QA '{question[:50]}' → {answer[:80]!r}")
        return answer

    def _point_sync(
        self, screenshot: Image.Image, query: str
    ) -> Optional[tuple[float, float]]:
        # Agent-format click prompt keeps MolmoWeb on-distribution for pointing.
        prompt = (
            f"Task: Click on {query}\n"
            "Previous actions: none\n\n"
            "Action:"
        )
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
        if x <= 100 and y <= 100:
            x, y = x / 100 * w, y / 100 * h
        return x, y

    # Format 2a: {"coordinate": [x, y]}
    m2 = re.search(r'"coordinate"\s*:\s*\[\s*([\d.]+)\s*,\s*([\d.]+)\s*\]', response)
    if m2:
        x, y = float(m2.group(1)), float(m2.group(2))
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
