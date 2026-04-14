"""
PointCheck — Modal Deployment

Three-model architecture:
  allenai/MolmoWeb-8B       — web navigation agent + element pointing (bfloat16, ~16 GB)
  allenai/Molmo-7B-D-0924   — screenshot QA + holistic WCAG analysis (4-bit NF4, ~4 GB)
  allenai/OLMo-3-7B-Instruct — executive summary narrative (bfloat16, ~14 GB)

Phase 1: MolmoWeb + MolmoQA co-resident during visual checks (~20 GB / 42.4 GB A100).
Phase 2: Both freed → OLMo loaded for narrative (~14 GB), then freed.
BFS site crawl via Playwright. GPU: A100-40GB.
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
        "tensorflow-cpu",  # required by Molmo-7B-D-0924 processor remote code
    )
    .run_commands("playwright install chromium && playwright install-deps")
    .add_local_dir("backend", remote_path="/app", copy=True)
    .run_commands("cd /app/app && python setup_models.py", gpu="any")
)


@app.function(
    image=image,
    gpu="A100-40GB",
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
