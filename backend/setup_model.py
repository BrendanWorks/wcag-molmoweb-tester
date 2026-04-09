"""
Pre-downloads and patches both AllenAI models:

  allenai/Olmo-3-7B-Instruct         — executive summary narrative generation
  allenai/Molmo2-4B                  — visual pointer for focus indicator confirmation

Run during Modal image build to cache weights (~22GB total).
"""
import torch

# ════════════════════════════════════════════════════════════════
#  1. Olmo-3-7B-Instruct  (text-only, no patches needed)
# ════════════════════════════════════════════════════════════════
from transformers import AutoModelForCausalLM, AutoTokenizer

print("Downloading OLMo3 tokenizer...")
AutoTokenizer.from_pretrained("allenai/Olmo-3-7B-Instruct")
print("Downloading OLMo3 weights...")
AutoModelForCausalLM.from_pretrained(
    "allenai/Olmo-3-7B-Instruct",
    torch_dtype=torch.bfloat16,
    device_map="auto",
)
print("OLMo3 cached.")

# ════════════════════════════════════════════════════════════════
#  2. Molmo2-4B  (vision-language, requires compat patches)
# ════════════════════════════════════════════════════════════════

# Patch 1: ROPE_INIT_FUNCTIONS missing 'default' in transformers 5.x
from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS
if "default" not in ROPE_INIT_FUNCTIONS:
    def _default_rope(config, device=None):
        base = config.rope_theta
        dim  = config.head_dim
        inv_freq = 1.0 / (
            base ** (torch.arange(0, dim, 2, dtype=torch.float32, device=device) / dim)
        )
        return inv_freq, 1.0
    ROPE_INIT_FUNCTIONS["default"] = _default_rope

# Patch 2: ProcessorMixin rejects unknown kwargs from Molmo2's remote code
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

from transformers import AutoProcessor, AutoModelForImageTextToText
print("Downloading Molmo2-4B processor...")
AutoProcessor.from_pretrained("allenai/Molmo2-4B", trust_remote_code=True, padding_side="left")

# Patch 3: cache_position[0] crash in modeling_molmo2.py
import glob
model_files = glob.glob(
    "/root/.cache/huggingface/modules/transformers_modules/allenai/Molmo2*/"
    "*/modeling_molmo2.py"
)
for mf in model_files:
    with open(mf) as f:
        code = f.read()
    if "cache_position[0] == 0:" in code and "is_prefill" not in code:
        code = code.replace(
            "if cache_position[0] == 0:",
            "is_prefill = (cache_position is not None and cache_position[0] == 0) "
            "or (cache_position is None and past_key_values is None)\n        if is_prefill:"
        )
        with open(mf, "w") as f:
            f.write(code)
        print(f"Patched {mf}")

print("Downloading Molmo2-4B weights...")
AutoModelForImageTextToText.from_pretrained(
    "allenai/Molmo2-4B",
    dtype=torch.bfloat16,
    device_map="auto",
    trust_remote_code=True,
)
print("Both models cached. Ready for deployment.")
