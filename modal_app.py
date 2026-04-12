"""
PointCheck — Modal Deployment

Two-model architecture:
  allenai/MolmoWeb-8B  — visual WCAG analysis (7 yes/no checks per page, bfloat16)
  allenai/OLMo-3-7B    — executive summary narrative (4-bit NF4, loaded after MolmoWeb freed)

BFS site crawl via Playwright. MolmoWeb and OLMo never resident simultaneously on A10G.
Entrypoint: backend/app/main.py (FastAPI + WebSocket streaming).
"""

import modal

app = modal.App("wcag-tester")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch",
        "torchvision",
        "transformers>=4.57.0",
        "Pillow",
        "einops",
        "requests",
        "numpy",
        "accelerate",
        "bitsandbytes",
        "playwright",
        "fastapi",
        "uvicorn[standard]",
        "websockets",
        "pydantic",
        "python-multipart",
    )
    .run_commands("playwright install chromium && playwright install-deps")
    .add_local_dir("backend", remote_path="/app", copy=True)
    .run_commands("cd /app/app && python setup_models.py", gpu="any")
)


@app.function(
    image=image,
    gpu="A10G",
    timeout=900,
    env={"PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"},
)
@modal.concurrent(max_inputs=5)
@modal.asgi_app()
def web():
    import sys
    sys.path.insert(0, "/app")

    # Runtime Molmo2 compat patches (mirrors setup_model.py)
    from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS
    if "default" not in ROPE_INIT_FUNCTIONS:
        import torch as _t
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
