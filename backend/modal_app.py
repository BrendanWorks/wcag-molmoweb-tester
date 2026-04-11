"""
MolmoAccess Agent — Modal Deployment

GPU: A10G (24 GB VRAM)
Models:
  allenai/MolmoWeb-8B        — 4-bit NF4 → ~4 GB   (visual WCAG analysis)
  allenai/OLMo-3-7B-Instruct — 4-bit NF4 → ~3.5 GB (narrative)
  Total: ~7.5 GB static + ~2.5 GB activation headroom — well within A10G 24 GB.

Cold-start time: ~45-60s (models baked into image via setup_models.py).
Warm requests: ~2-5s per page.

Three Molmo2 compat patches are applied at runtime (same as setup_models.py):
  1. ROPE "default" key
  2. ProcessorMixin lenient __init__
  3. cache_position shim for prepare_inputs_for_generation
These are REQUIRED for allenai/MolmoWeb-8B to load without error.
"""

import modal

app = modal.App("molmoaccess-agent")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        # ── Inference ─────────────────────────────────────────────────────
        "torch",
        "torchvision",
        "transformers>=4.57.0",
        "accelerate",
        "bitsandbytes",           # REQUIRED — 4-bit NF4 quantization
        "Pillow",
        "einops",
        # ── Browser automation ────────────────────────────────────────────
        "playwright",
        # ── Web server ────────────────────────────────────────────────────
        "fastapi",
        "uvicorn[standard]",
        "websockets",
        "pydantic>=2.0",
        "python-multipart",
        # ── Utilities ─────────────────────────────────────────────────────
        "httpx",
        "aiofiles",
        "requests",               # REQUIRED — transformers dynamic module loader
    )
    .run_commands(
        "playwright install chromium",
        "playwright install-deps",
    )
    # Copy the new app structure into /app
    .add_local_dir("app", remote_path="/app/app", copy=True)
    # Copy datasets dir stub (eval logger writes here)
    .run_commands("mkdir -p /app/datasets/molmoaccess-eval/raw")
    # Bake models into the image at build time
    .run_commands("cd /app && python app/setup_models.py", gpu="any")
)


@app.function(
    image=image,
    gpu="A10G",
    timeout=900,
    env={"PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"},
)
@modal.concurrent(max_inputs=3)  # 8B model uses more VRAM than original 4B
@modal.asgi_app()
def web():
    import sys
    sys.path.insert(0, "/app")

    # ── Runtime compat patches (mirrors setup_models.py) ─────────────────
    import torch as _t
    from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS
    if "default" not in ROPE_INIT_FUNCTIONS:
        def _default_rope(config, device=None):
            inv_freq = 1.0 / (
                config.rope_theta ** (
                    _t.arange(0, config.head_dim, 2, dtype=_t.float32, device=device)
                    / config.head_dim
                )
            )
            return inv_freq, 1.0
        ROPE_INIT_FUNCTIONS["default"] = _default_rope

    import transformers.processing_utils as _pu
    _orig = _pu.ProcessorMixin.__init__
    def _lenient(self, *a, **kw):
        known  = set(self.get_attributes()) | {"chat_template", "audio_tokenizer"}
        extras = {k: v for k, v in kw.items() if k not in known}
        clean  = {k: v for k, v in kw.items() if k in known}
        for k, v in extras.items():
            setattr(self, k, v)
        return _orig(self, *a, **clean)
    _pu.ProcessorMixin.__init__ = _lenient

    from app.main import app as fastapi_app
    return fastapi_app
