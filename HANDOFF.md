# MolmoAccess Agent — Handoff
**Last updated: 2026-04-11**

## What This Is

**MolmoAccess Agent** (PointCheck 2.0) is an open-source autonomous web accessibility agent. It crawls full sites, runs visual + programmatic WCAG 2.2 checks on every page, and generates plain-English reports — all driven by AI2's MolmoWeb-8B acting as both a browser action agent and a visual analysis engine.

| | |
|---|---|
| **Live site** | https://pointcheck.org |
| **Agent API** | https://brendanworks--molmoaccess-agent-web.modal.run |
| **Legacy API** | https://brendanworks--wcag-tester-web.modal.run (PointCheck v1, still live) |
| **GitHub** | https://github.com/BrendanWorks/PointCheck |
| **Stack** | Next.js 16 (Vercel) → FastAPI + WebSocket + Playwright + MolmoWeb-8B + OLMo-3-7B (Modal A10G 24 GB) |

---

## Architecture

```
┌──────────────────────────────┐        ┌───────────────────────────────────────────────────┐
│  Next.js 16 (Vercel)         │        │  FastAPI + Playwright + MolmoWeb-8B (Modal A10G)  │
│                              │        │                                                   │
│  • URL input + config        │◄──WS──►│  BFS Crawler (max 30 pages, depth 3)              │
│  • Live progress stream      │        │    ↓ per page:                                    │
│  • Per-page results          │        │  7 WCAG checks (programmatic + visual layer)       │
│  • Site-wide report          │        │    ↓                                              │
│  • JSON / CSV export         │        │  MolmoWebAgentLoop (interactive state discovery)   │
│                              │        │    ↓                                              │
└──────────────────────────────┘        │  Holistic vision analysis (full-page QA)           │
                                        │    ↓                                              │
                                        │  Video element pointing + flicker detection        │
                                        │    ↓                                              │
                                        │  OLMo-3-7B → site-wide narrative                  │
                                        └───────────────────────────────────────────────────┘
```

### Models

| Model | Role | VRAM |
|---|---|---|
| `allenai/MolmoWeb-8B` | Browser action agent + visual WCAG analysis. Outputs action dicts `{"thought": "...", "action": "mouse_click(x, y)"}`. Also used for QA and element pointing (`<point x="X" y="Y">`). 4-bit NF4 on CUDA. | ~4 GB |
| `allenai/OLMo-3-7B-Instruct` | Generates plain-English site-wide accessibility narrative after all pages are scanned. bfloat16. | ~14 GB |

**Total: ~18 GB — fits within A10G 24 GB with `expandable_segments:True`.**

Both models are baked into the Modal container image at build time (`setup_models.py`) — cold starts don't re-download weights. Warm requests: ~2–5s per page.

---

## Repo Layout

```
PointCheck/
├── backend/
│   ├── app/                        ← MolmoAccess Agent v2 (Phase 1)
│   │   ├── main.py                 FastAPI app, /api/crawl, /ws/crawl/{id}, legacy shims
│   │   ├── crawler.py              BFS Playwright crawler (30 pages, depth 3, robots.txt)
│   │   ├── molmo_agent.py          MolmoWebAgentLoop — screenshot → action → execute → repeat
│   │   ├── vision_analysis.py      Holistic WCAG QA + video pointing + flicker detection
│   │   ├── eval_logger.py          JSONL logger → datasets/molmoaccess-eval/
│   │   ├── report_generator.py     Multi-page report builder (backward-compatible)
│   │   ├── schemas.py              Pydantic v2 models (CrawlRequest, CrawlJobState)
│   │   ├── setup_models.py         Modal image build-time model download + patches
│   │   ├── models/
│   │   │   ├── molmo2.py           MolmoWebAnalyzer (analyze, point_to, screenshot utils)
│   │   │   └── olmo3.py            OLMo3Narrator (site-wide executive summary)
│   │   └── wcag_checks/
│   │       ├── base.py             BaseWCAGTest, TestResult dataclass
│   │       ├── keyboard_nav.py     2.1.1 · 2.1.2 · 2.4.1 · 2.4.3 + agent skip-nav + interactive discovery
│   │       ├── focus_indicator.py  2.4.7 — CSS + Molmo pointing
│   │       ├── zoom_test.py        1.4.4 · 1.4.10
│   │       ├── color_blindness.py  1.4.1 · 1.4.3
│   │       ├── form_errors.py      3.3.1–3.3.4 + agent form fill/submit
│   │       ├── page_structure.py   1.1.1 · 1.3.1 · 2.4.2 · 2.4.4 · 3.1.1 · 4.1.1 · 4.1.2
│   │       └── video_motion.py     1.2.1 · 1.2.2 · 2.2.2 · 2.3.1
│   ├── modal_app.py                ← Agent deployment (A10G, max_inputs=3)
│   ├── main.py                     ← PointCheck v1 (still used by legacy frontend)
│   └── wcag_agent.py               ← PointCheck v1 models (Molmo2-4B + OLMo-2-7B)
├── frontend/                       Next.js 16 (unchanged from v1 — legacy shims keep it working)
└── datasets/
    └── molmoaccess-eval/           JSONL benchmark dataset (one record per check per page)
        └── raw/
```

---

## API

### New (MolmoAccess Agent)

**`POST /api/crawl`**
```json
{
  "url": "https://example.com",
  "wcag_version": "2.2",
  "max_pages": 30,
  "max_depth": 3,
  "tests": ["keyboard_nav", "page_structure", "color_blindness", "focus_indicator",
            "zoom", "form_errors", "video_motion"]
}
```
Returns `{ "job_id": "...", "status": "queued" }`.

**`GET /api/crawl/{job_id}`** — Poll job state.

**`WS /ws/crawl/{job_id}`** — Stream events:

| Event type | When | Key fields |
|---|---|---|
| `status` | Lifecycle milestones | `message` |
| `page_start` | Navigator visits new page | `url`, `depth` |
| `test_start` | Each of 7 checks begins | `test_name`, `index`, `total` |
| `progress` | Within a check | `message` |
| `result` | Check complete | `data` (TestResult dict) |
| `test_complete` | Same as result (alias) | — |
| `page_done` | All checks for page done | `page_report` |
| `done` | Site crawl complete | `report` (full site report) |
| `error` | Fatal error | `message` |

### Legacy shims (v1 frontend compatibility)

**`POST /api/run`** → maps to `POST /api/crawl` with `max_pages=1`
**`WS /ws/{job_id}`** → maps to `WS /ws/crawl/{job_id}`

**`GET /health`** → `{ "status": "ok", "models_loaded": bool, "jobs": int }`

---

## The 7 WCAG Checks

| ID | Name | WCAG Criteria | Layers |
|---|---|---|---|
| `keyboard_nav` | Keyboard-Only Navigation | 2.1.1 · 2.1.2 · 2.4.1 · 2.4.3 | JS static scan + Tab traversal + **agent** (skip-nav functional test + interactive element discovery) |
| `focus_indicator` | Focus Visibility | 2.4.7 | CSS inspection + Molmo **pointing** (pixel-level confirmation, max 5 calls) |
| `zoom` | 200% Zoom / Reflow | 1.4.4 · 1.4.10 | CDP zoom + clipped element detection + Molmo visual |
| `color_blindness` | Color Blindness Simulation | 1.4.1 · 1.4.3 | Deuteranopia SVG filter + DOM contrast walk + Molmo visual |
| `form_errors` | Form Error Handling | 3.3.1 · 3.3.2 · 3.3.3 · 3.3.4 | **Agent** fill + submit (primary) + Playwright fallback + Molmo visual |
| `page_structure` | Page Structure & Semantics | 1.1.1 · 1.3.1 · 2.4.2 · 2.4.4 · 3.1.1 · 4.1.1 · 4.1.2 | JS eval + Molmo visual |
| `video_motion` | Video, Motion & Timing | 1.2.1 · 1.2.2 · 2.2.2 · 2.3.1 | JS video/audio/GIF/CSS-animation detection + Molmo **pointing** (caption button, play/pause) + **multi-frame flicker detection** |

### MolmoWebAgentLoop (molmo_agent.py)

The agent loop is what makes MolmoAccess different from a traditional Playwright scanner. MolmoWeb-8B decides what to interact with based on screenshots:

```
screenshot → _AGENT_PROMPT_TEMPLATE → MolmoWeb-8B inference
         ↓
parse {"thought": "...", "action": "mouse_click(45.2, 23.1)"}
         ↓
_execute_action() → page.mouse.click(px, py)   # coords denormalized from [0-100]
         ↓
asyncio.sleep(0.6)  → next screenshot → repeat
```

Actions supported: `mouse_click(x, y)`, `mouse_scroll(x, y, dir, amount)`, `key_press(key)`, `type_text(text)`, `done(reason)`.

Used in:
- **keyboard_nav**: clicks skip-nav and verifies focus jumped; opens hamburger menus and tests keyboard reachability of revealed items
- **form_errors**: fills fields with invalid data, submits, observes error state
- *(extensible to any check that needs interactive state discovery)*

---

## Critical Technical Knowledge

### MolmoWeb-8B — Three Mandatory Compat Patches

Applied in **both** `setup_models.py` (image build) **and** `modal_app.py` (runtime). Never remove any of them.

**Patch 1 — ROPE `"default"` key**
```python
from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS
if "default" not in ROPE_INIT_FUNCTIONS:
    def _default_rope(config, device=None):
        inv_freq = 1.0 / (config.rope_theta ** (
            torch.arange(0, config.head_dim, 2, dtype=torch.float32, device=device) / config.head_dim
        ))
        return inv_freq, 1.0
    ROPE_INIT_FUNCTIONS["default"] = _default_rope
```

**Patch 2 — ProcessorMixin lenient `__init__`**
```python
import transformers.processing_utils as _pu
_orig = _pu.ProcessorMixin.__init__
def _lenient(self, *a, **kw):
    known  = set(self.get_attributes()) | {"chat_template", "audio_tokenizer"}
    extras = {k: v for k, v in kw.items() if k not in known}
    clean  = {k: v for k, v in kw.items() if k in known}
    for k, v in extras.items(): setattr(self, k, v)
    return _orig(self, *a, **clean)
_pu.ProcessorMixin.__init__ = _lenient
```

**Patch 3 — `cache_position` shim** (wrap the model's own `prepare_inputs_for_generation`, not GenerationMixin — that bypasses image embedding)
```python
_orig_prepare = self.model.prepare_inputs_for_generation
def _patched_prepare(input_ids, past_key_values=None, cache_position=None, **kw):
    if cache_position is None:
        if past_key_values is None:
            cache_position = torch.arange(input_ids.shape[1], device=input_ids.device)
        else:
            past_len = past_key_values.get_seq_length()
            cache_position = torch.tensor([past_len], device=input_ids.device)
    return _orig_prepare(input_ids, past_key_values=past_key_values, cache_position=cache_position, **kw)
self.model.prepare_inputs_for_generation = _patched_prepare
```

### MolmoWeb-8B Inference — Do Not Change Without Reading This

1. **Remove `token_type_ids`** before `generate()` — causes "the the the" repetition loop if left in
2. **`AutoModelForImageTextToText`** not `AutoModelForCausalLM`
3. **`padding_side="left"`** on processor
4. **No sampling** — greedy decoding only (`do_sample=False`)
5. **`ConsecutiveNewlineSuppressor`** — custom `LogitsProcessor` that hard-bans newline token (ID 198) after 2 consecutive newlines. Standard `repetition_penalty` crashes because Molmo2 image-token IDs exceed `vocab_size`
6. **Always 4-bit NF4 on CUDA** — `bitsandbytes` must be in `modal_app.py` pip_install or the model loads in fp32 and OOMs
7. **Action coordinate space** — MolmoWeb outputs x, y in `[0, 100]` normalized viewport space. Denormalize: `px = (x / 100) * viewport_width`

### Video Multi-Frame Flicker Detection

`capture_video_frames()` in `vision_analysis.py` captures 3 frames at 200ms intervals, then computes a `motion_score` (fraction of pixels that changed >10% grayscale between consecutive frames). `motion_score > 0.30` sets `flicker_risk=True` → surfaces as WCAG 2.3.1 critical issue in the report.

### WebSocket + Screenshot Strategy

The `done` event strips `screenshot_b64` to stay under the 1 MB frame limit:
```python
def strip_b64(obj): ...
await ws.send_json({"type": "done", "report": strip_b64(final_report)})
```
The frontend collects `screenshot_b64` from individual `result` events as they stream, then splices them back in before rendering. Screenshots are never fetched via HTTP — no 404s on container recycle.

### Dataset Logging

Every check on every page is logged to `datasets/molmoaccess-eval/raw/<job_id>.jsonl` by `EvalLogger`. Each record captures: page URL, depth, check ID, WCAG criteria, pass/fail/warning, Molmo prompt, Molmo raw response, screenshot path. This builds the MolmoAccess-Eval benchmark dataset.

Override the dataset root: `export MOLMOACCESS_DATASET_ROOT=/your/path`

---

## Deployment

### Backend → Modal (Agent)
```bash
cd "/Users/brendanworks/Documents/Documents - Brendan's MacBook Pro/WCAG_Tool/backend"
modal deploy modal_app.py
# First deploy: ~8-9 min (bakes MolmoWeb-8B + OLMo-3-7B into image)
# Subsequent deploys: ~2 min if image is cached
```
**GPU:** A10G 24 GB  
**Concurrency:** `@modal.concurrent(max_inputs=3)` — 3 simultaneous crawl jobs per container  
**Timeout:** 900s per request  
**Env:** `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`

### Frontend → Vercel
Push to `main` — Vercel auto-deploys from `frontend/` root directory.
- Env var: `NEXT_PUBLIC_API_URL=https://brendanworks--molmoaccess-agent-web.modal.run`
- Domain: `pointcheck.org` — A record `@` → `76.76.21.21`, CNAME `www` → `cname.vercel-dns.com`

### Git
```bash
cd "/Users/brendanworks/Documents/Documents - Brendan's MacBook Pro/WCAG_Tool"
git add <files> && git commit -m "message" && git push
```

---

## Known Gotchas

| Issue | Notes |
|---|---|
| MolmoWeb agent action coordinate space | Coords in [0-100], NOT pixels. Always denormalize before Playwright: `px = x/100 * w` |
| `token_type_ids` in generate() inputs | Silent repetition loop. Always `inputs.pop("token_type_ids", None)` before `model.generate()` |
| Contrast false negative on transparent bg | `getEffectiveBg()` composites alpha layers up full DOM tree — do not simplify |
| Zoom false positive on skip links | Off-screen + `#`-href filter in clipped element JS |
| OLMo-3 hallucinated WCAG numbers | `_strip_hallucinated_criteria()` in `olmo3.py` removes invented criterion IDs |
| `bitsandbytes` missing from pip_install | Molmo loads in fp32, OOMs immediately on A10G alongside OLMo-3 |
| `requests` missing from Modal image | `transformers` dynamic module loader needs it — was missing, now in `modal_app.py` |
| `add_local_dir` path when deploying from `backend/` | Use `"app"` (relative), not `"backend/app"` — path is relative to the directory you run `modal deploy` from |
| Dataset root path in Modal container | `Path(__file__).parents[3]` wrong depth in container. `eval_logger.py` now walks up to find `datasets/` dir |
| Next.js CVE-2025-55182 | Patched — upgraded 15.2.4 → 16.2.2 |

---

## WCAG Coverage

| Principle | Criteria Covered |
|---|---|
| **Perceivable** | 1.1.1 · 1.2.1 · 1.2.2 · 1.3.1 · 1.4.1 · 1.4.3 · 1.4.4 · 1.4.10 |
| **Operable** | 2.1.1 · 2.1.2 · 2.2.2 · 2.3.1 · 2.4.1 · 2.4.2 · 2.4.3 · 2.4.4 · 2.4.7 · 2.5.5 |
| **Understandable** | 3.1.1 · 3.3.1 · 3.3.2 · 3.3.3 · 3.3.4 |
| **Robust** | 4.1.1 · 4.1.2 |

~90% of WCAG 2.2 Level AA success criteria covered programmatically + visually.

---

## Phase Roadmap

| Phase | Status | Description |
|---|---|---|
| **Phase 1** | ✅ Complete | BFS site crawler · 7 WCAG checks · MolmoWebAgentLoop · video pointing + flicker detection · eval logger |
| **Phase 2** | Planned | Remediation suggestions · side-by-side before/after · GitHub Actions CI integration |
| **Phase 3** | Planned | MolmoAccess-Eval benchmark · fine-tune on collected dataset · improved precision |
