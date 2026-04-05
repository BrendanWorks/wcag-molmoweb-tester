"""
WCAG 2.1 Accessibility Tester — Modal Deployment
Serves the FastAPI app on a GPU with MolmoWeb pre-loaded.
"""

import modal

app = modal.App("wcag-tester")

# Build the container image with all dependencies + model pre-downloaded
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch",
        "torchvision",
        "transformers>=5.0.0",
        "Pillow",
        "einops",
        "requests",
        "numpy",
        "accelerate",
        "playwright",
        "fastapi",
        "uvicorn[standard]",
        "websockets",
        "pydantic",
        "python-multipart",
    )
    .run_commands("playwright install chromium && playwright install-deps")
    # Copy backend code into the image (before model download so setup_model.py is available)
    .add_local_dir("backend", remote_path="/app", copy=True)
    # Download + patch model with all compat fixes applied
    .run_commands("cd /app && python setup_model.py", gpu="any")
)


@app.function(
    image=image,
    gpu="A10G",
    timeout=600,
)
@modal.concurrent(max_inputs=5)
@modal.asgi_app()
def web():
    import sys
    sys.path.insert(0, "/app")

    # Apply runtime patches (same as setup_model.py but for the running container)
    from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS
    if "default" not in ROPE_INIT_FUNCTIONS:
        import torch as _torch
        def _default_rope(config, device=None):
            base = config.rope_theta
            dim = config.head_dim
            inv_freq = 1.0 / (base ** (_torch.arange(0, dim, 2, dtype=_torch.float32, device=device) / dim))
            return inv_freq, 1.0
        ROPE_INIT_FUNCTIONS["default"] = _default_rope

    import transformers.processing_utils as _pu
    _orig = _pu.ProcessorMixin.__init__
    def _lenient(self, *a, **kw):
        known = set(self.get_attributes()) | {"chat_template", "audio_tokenizer"}
        extras = {k: v for k, v in kw.items() if k not in known}
        clean = {k: v for k, v in kw.items() if k in known}
        for k, v in extras.items():
            setattr(self, k, v)
        return _orig(self, *a, **clean)
    _pu.ProcessorMixin.__init__ = _lenient

    from main import app as fastapi_app
    return fastapi_app
