"""
Image build-time model download + compat-patch baking.

Run once during `modal deploy` (gpu="any" build step) to download and
serialize both models into the container image, eliminating cold-start
download time. The three Molmo2 compat patches are applied here so the
serialized state is already patched when the container warms up.

This script is ONLY called by the Modal image build; it does not import
app/ modules (avoids circular dependency at image build time).
"""

import sys
import torch


def apply_molmo2_patches():
    """Apply the three required Transformers 5.x compat patches for Molmo2/MolmoWeb."""

    # Patch 1: ROPE "default" key
    from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS
    if "default" not in ROPE_INIT_FUNCTIONS:
        def _default_rope(config, device=None):
            inv_freq = 1.0 / (
                config.rope_theta ** (
                    torch.arange(0, config.head_dim, 2, dtype=torch.float32, device=device)
                    / config.head_dim
                )
            )
            return inv_freq, 1.0
        ROPE_INIT_FUNCTIONS["default"] = _default_rope
        print("[setup] ROPE patch applied")

    # Patch 2: ProcessorMixin lenient __init__
    import transformers.processing_utils as _pu
    _orig_init = _pu.ProcessorMixin.__init__
    def _lenient_init(self, *args, **kwargs):
        known  = set(self.get_attributes()) | {"chat_template", "audio_tokenizer"}
        extras = {k: v for k, v in kwargs.items() if k not in known}
        clean  = {k: v for k, v in kwargs.items() if k in known}
        for k, v in extras.items():
            setattr(self, k, v)
        return _orig_init(self, *args, **clean)
    _pu.ProcessorMixin.__init__ = _lenient_init
    print("[setup] ProcessorMixin patch applied")


def download_molmoweb():
    from transformers import AutoProcessor, AutoModelForImageTextToText

    model_name = "allenai/MolmoWeb-8B"
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    print(f"[setup] Downloading {model_name} on {device}...")

    apply_molmo2_patches()

    AutoProcessor.from_pretrained(model_name, trust_remote_code=True, padding_side="left")

    model_kwargs: dict = {"trust_remote_code": True, "dtype": dtype}
    if device == "cuda":
        model_kwargs["device_map"] = "auto"

    model = AutoModelForImageTextToText.from_pretrained(model_name, **model_kwargs)

    # Apply cache_position patch (patch 3) so the baked image has it
    _orig_prepare = model.prepare_inputs_for_generation
    def _patched_prepare(input_ids, past_key_values=None, cache_position=None, **kw):
        if cache_position is None:
            if past_key_values is None:
                cache_position = torch.arange(input_ids.shape[1], device=input_ids.device)
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
        return _orig_prepare(input_ids, past_key_values=past_key_values, cache_position=cache_position, **kw)
    model.prepare_inputs_for_generation = _patched_prepare
    print("[setup] cache_position patch applied")
    print(f"[setup] {model_name} ready")

    # Free VRAM immediately — OLMo will be downloaded next and they must not
    # coexist in memory (MolmoWeb bf16 ~16 GB + OLMo bf16 ~14 GB > 24 GB).
    del model
    if device == "cuda":
        torch.cuda.empty_cache()


def download_olmo3():
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    model_name = "allenai/OLMo-3-7B-Instruct"
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[setup] Downloading {model_name} on {device}...")

    AutoTokenizer.from_pretrained(model_name)

    model_kwargs: dict = {}
    if device == "cuda":
        model_kwargs["device_map"] = "auto"
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )
    else:
        model_kwargs["dtype"] = torch.float32

    AutoModelForCausalLM.from_pretrained(model_name, **model_kwargs)
    print(f"[setup] {model_name} ready")


if __name__ == "__main__":
    print("[setup] Baking models into Modal image...")
    download_molmoweb()
    download_olmo3()
    print("[setup] All models downloaded and patched ✓")
