"""
Downloads and patches MolmoWeb for compatibility with transformers 5.x.
Run this during image build to pre-cache everything.
"""

# 1) Patch ROPE_INIT_FUNCTIONS
from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS
if "default" not in ROPE_INIT_FUNCTIONS:
    import torch
    def _default_rope(config, device=None):
        base = config.rope_theta
        dim = config.head_dim
        inv_freq = 1.0 / (base ** (torch.arange(0, dim, 2, dtype=torch.float32, device=device) / dim))
        return inv_freq, 1.0
    ROPE_INIT_FUNCTIONS["default"] = _default_rope

# 2) Patch ProcessorMixin to accept unknown kwargs
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

# 3) Download config + processor
from transformers import AutoConfig, AutoProcessor
print("Downloading config...")
AutoConfig.from_pretrained("allenai/MolmoWeb-4B", trust_remote_code=True)
print("Downloading processor...")
AutoProcessor.from_pretrained("allenai/MolmoWeb-4B", trust_remote_code=True)
print("Processor cached.")

# 4) Patch the modeling code for cache_position compatibility
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

# 5) Download model weights
from transformers import AutoModelForImageTextToText
import torch
print("Downloading model weights (this takes a while)...")
AutoModelForImageTextToText.from_pretrained(
    "allenai/MolmoWeb-4B",
    dtype=torch.bfloat16,
    device_map="auto",
    trust_remote_code=True,
)
print("Model cached and patched. Ready for deployment.")
