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
    # Pre-download the model into the image so cold starts are fast
    .run_commands(
        "python -c \""
        "from transformers import AutoModelForImageTextToText, AutoProcessor, AutoConfig; "
        "AutoConfig.from_pretrained('allenai/MolmoWeb-4B', trust_remote_code=True); "
        "AutoProcessor.from_pretrained('allenai/MolmoWeb-4B', trust_remote_code=True); "
        "print('Processor cached'); "
        "\"",
        gpu="any",
    )
    .run_commands(
        "python -c \""
        "from transformers import AutoModelForImageTextToText; "
        "import torch; "
        "AutoModelForImageTextToText.from_pretrained("
        "'allenai/MolmoWeb-4B', "
        "dtype=torch.bfloat16, "
        "device_map='auto', "
        "trust_remote_code=True"
        "); "
        "print('Model cached'); "
        "\"",
        gpu="any",
    )
)

# Copy our backend code into the image
backend_mount = modal.Mount.from_local_dir(
    "backend",
    remote_path="/app",
    condition=lambda path: not any(
        x in path for x in ["venv/", "__pycache__", "screenshots/", ".pyc"]
    ),
)


@app.function(
    image=image,
    gpu="A10G",
    timeout=600,
    mounts=[backend_mount],
    allow_concurrent_inputs=5,
)
@modal.asgi_app()
def web():
    import sys
    sys.path.insert(0, "/app")

    # Apply the same compatibility patches as wcag_agent.py
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

    # Patch the cached model code for cache_position compatibility
    import importlib
    import glob
    model_files = glob.glob("/root/.cache/huggingface/modules/transformers_modules/allenai/MolmoWeb*/*/modeling_molmo2.py")
    for mf in model_files:
        with open(mf, "r") as f:
            code = f.read()
        if "cache_position[0] == 0:" in code and "is_prefill" not in code:
            code = code.replace(
                "if cache_position[0] == 0:",
                "is_prefill = (cache_position is not None and cache_position[0] == 0) or (cache_position is None and past_key_values is None)\n        if is_prefill:"
            )
            with open(mf, "w") as f:
                f.write(code)
            print(f"Patched {mf}")

    from main import app as fastapi_app
    return fastapi_app
