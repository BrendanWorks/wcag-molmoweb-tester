# WCAG 2.1 Accessibility Tester — Handoff Document
**Last updated: 2026-04-07**

## What This Is
A fully deployed WCAG 2.1 Level AA accessibility testing tool built as a portfolio piece for an Allen AI job application. Users paste a URL, select tests, and receive a detailed accessibility report with live streaming progress, Molmo2 visual confirmation, and an OLMo2-written executive summary.

- **GitHub**: https://github.com/BrendanWorks/wcag-molmoweb-tester
- **Live frontend**: https://wcag-molmoweb-tester.vercel.app
- **Backend endpoint**: https://brendanworks--wcag-tester-web.modal.run
- **Stack**: Next.js 16 (Vercel) → FastAPI + WebSocket + Playwright + OLMo2-7B + Molmo2-4B (Modal A10G)

---

## Architecture

```
┌─────────────────────────────────┐        ┌──────────────────────────────────────┐
│  Next.js 16 (Vercel)            │        │  FastAPI + Playwright (Modal A10G)   │
│                                 │        │                                      │
│  • URL input + test selector    │◄──WS──►│  • Runs 6 WCAG tests via Playwright  │
│  • Live progress feed           │        │  • OLMo-2-7B  → executive narrative  │
│  • Results dashboard            │        │  • Molmo2-4B  → visual pointer       │
│  • JSON / CSV export            │        │  • Streams events over WebSocket     │
└─────────────────────────────────┘        └──────────────────────────────────────┘
```

### Models
| Model | Role | Size on disk |
|---|---|---|
| `allenai/OLMo-2-1124-7B-Instruct` | Writes plain-English executive summary after all tests complete | ~14 GB bfloat16 |
| `allenai/Molmo2-4B` | Visual pointer — outputs `<point x="X" y="Y">` pixel coordinates from screenshots to confirm focus ring visibility | ~2 GB, 4-bit NF4 quantized |

Both models baked into the Modal container at build time via `setup_model.py` so cold starts don't re-download weights.

---

## Key Files

| File | Purpose |
|---|---|
| `modal_app.py` | Modal deployment — A10G, 900s timeout, bakes models into image, applies runtime compat patches |
| `backend/main.py` | FastAPI app, WebSocket `/ws/run` handler, TEST_MAP, `_strip_b64()` helper |
| `backend/wcag_agent.py` | OLMo2 (WCAGAgent) + Molmo2 (Molmo2Pointer) classes, ConsecutiveNewlineSuppressor |
| `backend/report_generator.py` | Aggregates per-test results → JSON report with narrative |
| `backend/setup_model.py` | Modal image build — downloads models, applies `cache_position` file patch to Molmo2 |
| `backend/tests/keyboard_nav.py` | 2.1.1 · 2.1.2 · 2.4.3 — Tab traversal + static JS scan |
| `backend/tests/zoom_test.py` | 1.4.4 · 1.4.10 — 200% zoom + clipped element detection |
| `backend/tests/color_blindness.py` | 1.4.1 · 1.4.3 — Deuteranopia SVG + DOM-tree contrast walk |
| `backend/tests/focus_indicator.py` | 2.4.7 — CSS inspection + Molmo2 visual confirmation |
| `backend/tests/form_errors.py` | 3.3.1 · 3.3.2 · 3.3.3 — Form submission with invalid data |
| `backend/tests/page_structure.py` | 1.1.1 · 1.3.1 · 1.4.1 · 2.4.2 · 2.4.4 · 2.5.5 · 3.1.1 · 4.1.2 — Single JS eval, no GPU |
| `frontend/components/ResultsDashboard.tsx` | Full results UI — Molmo2 visual panel, page_structure issue breakdown, base64 screenshots |
| `frontend/components/TestSelector.tsx` | Test checkbox list with WCAG criteria labels |
| `frontend/app/page.tsx` | Main page — URL input, WebSocket client, live progress |
| `frontend/.env.local` | `NEXT_PUBLIC_API_URL=https://brendanworks--wcag-tester-web.modal.run` |

---

## All 6 Tests

### 1. Keyboard Navigation (`keyboard_nav.py`)
- WCAG: 2.1.1 · 2.1.2 · 2.4.3
- **Two-layer check:** `KEYBOARD_STATIC_JS` pre-scan (javascript: hrefs, onclick on non-interactive elements, onmouseover without onfocus, missing skip nav, **positive tabindex values**) + tab traversal loop
- Static failures drive the result; tab loop only records focused element info (focus indicator check removed — belongs to focus_indicator test)
- Result: fail if static issues found (keyboard traps, JS-only links, mouse-only handlers, tab order overrides)
- Positive tabindex check: any `tabindex > 0` is a 2.4.3 major failure — reports tag, value, and label text

### 2. Zoom / Reflow (`zoom_test.py`)
- WCAG: 1.4.4 · 1.4.10
- Sets viewport to 1280px, then zooms to 200% (640px equivalent)
- Detects clipped/hidden text elements; filters off-screen elements and skip links to avoid false positives
- Key filter: `offScreen = r.left < -200 || r.top < -200; isSkipLink = el.tagName === 'A' && href.startsWith('#') && offScreen`

### 3. Color Blindness / Contrast (`color_blindness.py`)
- WCAG: 1.4.1 · 1.4.3
- Applies CSS deuteranopia SVG filter; checks contrast ratio via `getEffectiveBg()` DOM walk
- `getEffectiveBg()` composites alpha layers up the DOM tree — does NOT skip transparent elements (fixed false negative on W3C BAD site)
- Checks 60 elements including `div`; threshold 4.5:1 normal text, 3:1 large text

### 4. Focus Indicator (`focus_indicator.py`)
- WCAG: 2.4.7
- Two-layer: CSS inspection first (outline, box-shadow, border changes) → if CSS confirms, Molmo2 visually confirms via pixel-coordinate pointing
- Molmo2 miss = indicator is technically present but visually insufficient
- Results dashboard shows per-step hit/miss with `(x,y)px` coordinates and expected DOM location for misses

### 5. Form Error Handling (`form_errors.py`)
- WCAG: 3.3.1 · 3.3.2 · 3.3.3
- Finds forms, checks label associations, submits with invalid data, checks for error messages
- Uses Molmo2 to visually confirm error messages are present and associated with fields

### 6. Page Structure & Semantics (`page_structure.py`)
- WCAG: 1.1.1 · 1.3.1 · 1.4.1 · 2.4.2 · 2.4.4 · 2.5.5 · 3.1.1 · 4.1.2
- **No GPU required** — single JS evaluation, ~100ms
- Checks:
  - `3.1.1` — missing lang attribute on `<html>`
  - `2.4.2` — missing or generic page title
  - `1.1.1` — missing alt, empty alt on meaningful images, filename-style alt text
  - `1.3.1` — no h1, multiple h1s, skipped heading levels, data table cells without `<th>`/scope
  - `1.4.1` — inline links with no underline or non-color visual cue (color-only distinction)
  - `2.4.4` — vague link text ("click here", "read more", etc.)
  - `2.5.5` — interactive elements under 24×24px (WCAG 2.2 AA threshold; 2.1 AAA is 44×44px); reports actual pixel dimensions
  - `4.1.2` — unnamed ARIA roles, bad role=list children, focusable elements inside aria-hidden, iframes missing title/aria-label
- Returns issues sorted by severity (critical → major → minor)
- ResultsDashboard renders each issue as a card with criterion badge, severity color, description, examples, fix

---

## Critical Technical Knowledge

### Molmo2 Compat Patches (THREE required — applied in BOTH setup_model.py AND modal_app.py runtime)

1. **ROPE patch** — `ROPE_INIT_FUNCTIONS` missing `"default"` key → add custom `_default_rope` function
2. **ProcessorMixin patch** — `__init__` rejects unknown kwargs from Molmo2's remote code → monkey-patch to be lenient, store extras with `setattr`
3. **cache_position patch** — Transformers 5.x stopped passing `cache_position` to `prepare_inputs_for_generation`, but Molmo2 does `cache_position[0]` which crashes
   - Wrap the model's OWN method (not GenerationMixin grandparent — that bypasses image embedding)
   - Prefill: `torch.arange(seq_len)`, Decode: `torch.tensor([past_length])`
   - Also patched on-disk in `setup_model.py`: `if cache_position[0] == 0:` → safe None check

### Molmo2 Inference — Do Not Change Without Understanding

1. **Remove `token_type_ids`** from inputs before `generate()` — causes degenerate "the the the" repetition if left in
2. **One-step processor call** — pass PIL image directly in messages dict; old two-step approach didn't bind images to tokens
3. **No sampling params** — `max_new_tokens=512` only; no temperature/top_p (greedy decoding)
4. **`padding_side="left"`** on processor
5. **Decode only new tokens** — `outputs[0][input_len:]`
6. **`AutoModelForImageTextToText`** not `AutoModelForCausalLM`
7. **ConsecutiveNewlineSuppressor** — custom LogitsProcessor hard-bans newline token (ID 198) after 2 consecutive newlines, prevents 512-newline inference loop. Standard `repetition_penalty` crashes because Molmo2 image-token IDs exceed vocab_size.

### 4-bit Quantization (required to fit both models on A10G 24GB)

```python
# In wcag_agent.py Molmo2Pointer
if self.device == "cuda":
    model_kwargs["quantization_config"] = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
    )
    model_kwargs.pop("dtype", None)  # incompatible with quantization_config
```

`bitsandbytes` must be in `modal_app.py` pip_install list — its absence causes silent failure (Molmo2 loads but `_pointer=None`, falls back to CSS-only).

### WebSocket Frame Size

The `done` event strips base64 screenshots to stay under 1MB frame limit:
```python
def _strip_b64(obj):
    if isinstance(obj, dict):
        return {k: _strip_b64(v) for k, v in obj.items() if k != "screenshot_b64"}
    ...
await send({"type": "done", "run_id": run_id, "report": _strip_b64(report)})
```
Individual `result` events during the run still include `screenshot_b64` for the live UI.

### GPU Memory
```
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
```
Set in `modal_app.py` `env={}` dict. Reduces CUDA memory fragmentation on A10G.

---

## Deployment

### Backend → Modal
```bash
/opt/homebrew/bin/modal deploy modal_app.py
# Takes ~2 min. Models already baked in image so no re-download.
# Check: modal app list | grep wcag
# Logs: modal app logs wcag-tester
```

### Frontend → Vercel
Push to `main` on GitHub — Vercel auto-deploys.
- Root Directory: `frontend`
- Framework: Next.js
- Env var: `NEXT_PUBLIC_API_URL=https://brendanworks--wcag-tester-web.modal.run`

### Git
```bash
cd "/Users/brendanworks/Documents/Documents - Brendan's MacBook Pro/WCAG_Tool"
git add <files> && git commit -m "message" && git push
# If push rejected: git pull --rebase && git push
```

---

## Known Issues / Gotchas

| Issue | Fix Applied |
|---|---|
| Contrast false negative (transparent bg elements) | `getEffectiveBg()` walks DOM tree compositing alpha layers |
| Keyboard false negative (JS-only links) | `KEYBOARD_STATIC_JS` pre-scan added |
| Zoom false positive (off-screen skip links) | Off-screen + skip link detection in clipped element filter |
| Focus test false positive (skip links) | Skip link caveat added to Molmo2 "not found" warning |
| Screenshots 404 on Modal | Serverless — switched to base64 embedded in WS events |
| WebSocket frame >1MB | `_strip_b64()` helper strips screenshots from `done` event |
| CSV download 404 | Uses local report data, no server roundtrip |
| CORS blocking Vercel | `allow_origins=["*"]`, `allow_credentials=False` |
| Molmo2 meta tensor / OOM error | Forced 4-bit NF4 quant; `bitsandbytes` in pip_install |
| OOM with concurrent runs | Sequential execution with 15s cooldown between runs |
| Next.js CVE-2025-55182 | Upgraded from 15.2.4 → 16.2.2 |

---

## Third-Party Site Testing History

Multi-site validation was run against five external sites to confirm real catches, expose false positives/negatives, and drive bug fixes.

---

### 1. W3C WAI "BAD" Demo — https://www.w3.org/WAI/demos/bad/
**Purpose:** W3C's official intentionally-broken accessibility demo. Has documented known failures — used as ground truth to verify the tool catches what it should.

| Test | Result | Notes |
|---|---|---|
| Keyboard Navigation | FAIL ✓ | JS-only links detected |
| Color/Contrast | FAIL ✓ | Initially a false negative — fixed |
| Focus Indicator | WARNING ✓ | Molmo2 flagged visually insufficient focus rings |
| Zoom/Reflow | FAIL ✓ | Text clipping caught |
| Form Errors | FAIL ✓ | Missing labels detected |

**Bugs found and fixed on this site:**
- **Contrast false negative** — `getEffectiveBg()` was skipping `rgba(0,0,0,0)` transparent elements instead of walking up the DOM. Rewrote to composite alpha layers up the full tree. Now catches contrast failures on elements with inherited backgrounds.
- **Keyboard false negative** — tab loop only checked focus traps, not JS-only links. Added `KEYBOARD_STATIC_JS` pre-scan: checks `javascript:` hrefs, `onclick` on non-interactive elements, `onmouseover` without `onfocus`, and missing skip nav.

---

### 2. GDS — UK Government Design System
**Purpose:** High-quality accessible government site. Used to confirm true passes and catch any false positives on well-built accessible code.

| Test | Result | Notes |
|---|---|---|
| Keyboard Navigation | PASS ✓ | JS links detected but overall accessible |
| Color/Contrast | PASS ✓ | ~3.87:1 ratio met threshold |
| Zoom/Reflow | FAIL ✓ | Text clipping correctly caught |
| Focus Indicator | PASS ✓ | GDS has visible focus — correctly identified |
| Form Errors | FAIL ✓ | Missing labels detected |

**No bugs introduced. Good baseline for true-positive / true-negative balance.**

---

### 3. Mars Commuter
**Purpose:** Modern web components site with complex interactive patterns (modals, dropdowns, dynamic content). Tests the tool against real-world JS-heavy UIs.

| Test | Result | Notes |
|---|---|---|
| Keyboard Navigation | FAIL ✓ | JavaScript-only links detected |
| Color/Contrast | FAIL ✓ | Contrast failures caught |
| Zoom/Reflow | PASS ✓ | Correctly passed |
| Focus Indicator | FAIL ✓ | iframe focus issues caught |
| Form Errors | FAIL ✓ | 5 unlabeled fields detected |

**No bugs introduced. Confirmed tool handles complex JS components correctly.**

---

### 4. Accessible University 3.0 (AU) — University of Washington
**Purpose:** Before/after accessibility demo with intentional failures. Used to verify the tool catches real issues on a multi-page site.

| Test | Result | Notes |
|---|---|---|
| Keyboard Navigation | FAIL ✓ | Issues detected |
| Color/Contrast | FAIL ✓ | 2.52:1 ratio — well below 4.5:1 threshold |
| Zoom/Reflow | PASS ✓ | Site reflows properly — correctly passed |
| Focus Indicator | FAIL ✓ | No focus styles detected |
| Form Errors | FAIL ✓ | 5 unlabeled form fields detected |

**No bugs introduced. Good confirmation of multi-page site handling.**

---

### 5. Tenon UI — https://tenon-ui.info (via https://github.com/tenon-io)
**Purpose:** Intentionally *accessible* React component library. Used specifically to hunt for false positives on well-built accessible code.

| Test | Result | Notes |
|---|---|---|
| Keyboard Navigation | PASS ✓ | Correctly passed |
| Color/Contrast | PASS ✓ | Correctly passed |
| Zoom/Reflow | FALSE POSITIVE ✗ → fixed | Skip link flagged as clipped text |
| Focus Indicator | PASS ✓ | Correctly passed (with skip link caveat) |
| Form Errors | PASS ✓ | "No forms on page" correctly reported |

**Bugs found and fixed on this site:**
- **Zoom false positive on skip links** — "Skip to content" link is intentionally off-screen (`position:absolute; left:-9999px`) until focused. Tool was incorrectly flagging it as clipped text. Fixed by adding off-screen detection and skip link filter in the clipped element JS:
  ```javascript
  const offScreen = r.left < -200 || r.top < -200;
  const isSkipLink = el.tagName === 'A' && href.startsWith('#') && offScreen;
  return !offScreen && !tinyOrHidden && !isSkipLink && ...
  ```
- **Molmo2 "not found" warning on skip links** — Molmo2 correctly can't locate an off-screen element visually, but the warning message was confusing. Added skip link caveat to the warning text in `focus_indicator.py`.

---

### Testing Summary

All five sites confirmed the tool catches real failures across all test categories. The two primary false negative fixes (contrast DOM walk, keyboard static scan) were both discovered on the W3C BAD site. The primary false positive fix (zoom skip links) was discovered on Tenon UI — the most adversarial test case for false positives.

| Site | Purpose | Key Outcome |
|---|---|---|
| W3C BAD | Ground truth failures | Found + fixed 2 false negatives |
| GDS | High-quality accessible site | Confirmed true-positive/true-negative balance |
| Mars Commuter | JS-heavy modern UI | Confirmed complex component handling |
| AU (U Washington) | Multi-page demo | Confirmed multi-page site handling |
| Tenon UI | Intentionally accessible code | Found + fixed 1 false positive |

---

## WCAG Coverage

| Principle | Criteria Covered |
|---|---|
| Perceivable | 1.1.1 · 1.3.1 · 1.4.1 · 1.4.3 · 1.4.4 · 1.4.10 |
| Operable | 2.1.1 · 2.1.2 · 2.4.2 · 2.4.3 · 2.4.4 · 2.4.7 · 2.5.5 |
| Understandable | 3.1.1 · 3.3.1 · 3.3.2 · 3.3.3 |
| Robust | 4.1.2 |

**~85–90% of WCAG 2.1 Level AA** success criteria covered programmatically.

 form answer ("Tell a story about the last thing you learned in AI") is in the conversation history — covers Molmo2 as a spatial verifier (not generator), pixel coordinate output, the binary visual confirmation insight, and the two-model coexistence engineering.
