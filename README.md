# WCAG 2.1 Accessibility Tester

An automated WCAG 2.1 Level AA testing tool powered by two Allen AI open-source models. Paste a URL, select tests, and get a detailed accessibility report in seconds — including a written narrative and Molmo2 visual confirmation of focus indicators.

**Live demo:** [wcag-molmoweb-tester.vercel.app](https://wcag-molmoweb-tester.vercel.app)

---

## What It Does

The tool runs up to six accessibility tests against any public URL using a headless Chromium browser (Playwright). Results stream back live over WebSocket. When all tests finish, an LLM writes a plain-English executive summary.

| Test | WCAG Criteria | Method |
|---|---|---|
| Keyboard-Only Navigation | 2.1.1 · 2.1.2 · 2.4.3 | Tab traversal + static JS scan for mouse-only handlers |
| 200% Zoom / Reflow | 1.4.4 · 1.4.10 | Browser zoom + clipped-element detection |
| Color-Blindness Simulation | 1.4.1 · 1.4.3 | Deuteranopia SVG filter + DOM-tree contrast walk |
| Focus Visibility Check | 2.4.7 | CSS inspection + **Molmo2-4B visual confirmation** |
| Form Error Handling | 3.3.1 · 3.3.2 · 3.3.3 | Form submission with invalid data |
| Page Structure & Semantics | 1.1.1 · 1.3.1 · 2.4.2 · 2.4.4 · 3.1.1 · 4.1.2 | Single JS evaluation (~100 ms, no GPU) |

---

## Architecture

```
┌─────────────────────────────────┐        ┌──────────────────────────────────────┐
│  Next.js 16 (Vercel)            │        │  FastAPI + Playwright (Modal A10G)   │
│                                 │        │                                      │
│  • URL input + test selector    │◄──WS──►│  • Runs 6 WCAG tests                │
│  • Live progress feed           │        │  • OLMo-2-7B  → narrative            │
│  • Results dashboard            │        │  • Molmo2-4B  → visual pointer       │
│  • JSON / CSV export            │        │  • Streams results over WebSocket    │
└─────────────────────────────────┘        └──────────────────────────────────────┘
```

### Models

| Model | Role | Size |
|---|---|---|
| [allenai/OLMo-2-1124-7B-Instruct](https://huggingface.co/allenai/OLMo-2-1124-7B-Instruct) | Writes the plain-English executive summary after all tests complete | ~14 GB bfloat16 |
| [allenai/Molmo2-4B](https://huggingface.co/allenai/Molmo2-4B) | Vision-language model — given a screenshot, outputs pixel coordinates of the focused element to confirm the focus ring is **visually** present (not just technically in the DOM) | ~2 GB 4-bit NF4 |

Molmo2's output format is `<point x="42.3" y="67.1">`. If it cannot locate the focused element in the screenshot, the element passes the CSS check but fails visual confirmation — a class of failure that DOM inspection alone cannot catch.

---

## Key Technical Details

- **WebSocket streaming** — test events (`test_start`, `result`, `test_complete`, `done`) push to the browser in real time
- **Base64 screenshots** — Modal is serverless; screenshots are embedded directly in result events rather than saved to disk
- **4-bit quantization** — Molmo2 uses `BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4")` to fit alongside OLMo2 on a single A10G (24 GB VRAM)
- **DOM-tree contrast walk** — `getEffectiveBg()` composites alpha layers up the DOM tree to find the actual rendered background, avoiding false passes on transparent elements
- **Static JS keyboard scan** — before tab traversal, scans the DOM for `javascript:` hrefs, `onclick` on non-interactive elements, and missing skip navigation
- `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` — reduces CUDA memory fragmentation on the A10G

---

## Project Structure

```
.
├── modal_app.py              # Modal deployment (image build + ASGI wrapper)
├── backend/
│   ├── main.py               # FastAPI app, WebSocket run handler
│   ├── wcag_agent.py         # OLMo2 (narrative) + Molmo2 (visual pointer)
│   ├── report_generator.py   # Aggregates results → JSON/CSV report
│   ├── requirements.txt
│   └── tests/
│       ├── base_test.py
│       ├── keyboard_nav.py
│       ├── zoom_test.py
│       ├── color_blindness.py
│       ├── focus_indicator.py
│       ├── form_errors.py
│       └── page_structure.py
└── frontend/
    ├── app/
    │   └── page.tsx          # Main page (URL input, WebSocket client)
    └── components/
        ├── TestSelector.tsx  # Test checkbox list grouped by phase
        └── ResultsDashboard.tsx  # Results, Molmo2 panel, issue breakdown
```

---

## Running Locally

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

uvicorn main:app --reload --port 8000
```

The first run downloads OLMo2 (~14 GB) and Molmo2 (~4 GB). A CUDA GPU is strongly recommended — CPU inference is very slow.

### Frontend

```bash
cd frontend
npm install

# Point at your local backend
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local

npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

---

## Deploying

### Backend → Modal

```bash
pip install modal
modal deploy modal_app.py
```

The Modal image bakes both models into the container at build time (`setup_model.py`) so cold starts don't re-download weights.

### Frontend → Vercel

Push to `main`. Vercel auto-deploys from the `frontend/` root directory.

Set the environment variable in your Vercel project:

```
NEXT_PUBLIC_API_URL=https://<your-modal-endpoint>.modal.run
```

---

## Validation — Multi-Site Testing

The tool was validated against five external sites to confirm real catches, expose false positives/negatives, and drive bug fixes.

| Site | Purpose | Key Outcome |
|---|---|---|
| [W3C WAI "BAD" Demo](https://www.w3.org/WAI/demos/bad/) | W3C's official intentionally-broken accessibility demo — ground truth | Found + fixed 2 false negatives |
| [UK Government Design System (GDS)](https://design-system.service.gov.uk) | High-quality accessible government site | Confirmed true-positive / true-negative balance |
| Mars Commuter | JS-heavy site with modals, dropdowns, dynamic content | Confirmed correct handling of complex components |
| [Accessible University 3.0](https://www.washington.edu/accesscomputing/AU/) (U. Washington) | Before/after accessibility demo with intentional failures | Confirmed multi-page site handling |
| [Tenon UI](https://tenon-ui.info) | Intentionally *accessible* React component library — adversarial false-positive test | Found + fixed 1 false positive |

### Results by site

**W3C WAI "BAD" Demo** — all documented failures caught (keyboard JS-only links, contrast, focus, zoom, form labels). Two bugs fixed:
- **Contrast false negative** — `getEffectiveBg()` was skipping `rgba(0,0,0,0)` transparent elements. Rewrote to composite alpha layers up the full DOM tree, catching contrast failures on elements with inherited backgrounds.
- **Keyboard false negative** — tab traversal alone missed JS-only links. Added `KEYBOARD_STATIC_JS` pre-scan for `javascript:` hrefs, `onclick` on non-interactive elements, `onmouseover` without `onfocus`, and missing skip navigation.

**GDS** — no false positives on well-built accessible code. Zoom correctly flagged text clipping; focus, contrast, and keyboard all passed cleanly.

**Mars Commuter** — keyboard JS links detected, contrast failures caught, 5 unlabeled form fields identified. Zoom correctly passed. Tool handled iframe focus issues correctly.

**Accessible University 3.0** — contrast failure caught at 2.52:1 (well below 4.5:1 threshold), 5 unlabeled form fields detected, focus styles correctly flagged as absent. Zoom correctly passed on a site that reflows properly.

**Tenon UI** — all tests correctly passed except one false positive fixed:
- **Zoom false positive on skip links** — "Skip to content" links are intentionally off-screen (`position:absolute; left:-9999px`) until focused. Tool was incorrectly flagging them as clipped text. Fixed by adding off-screen detection and skip link filter in the clipped element JS scan.

---

## WCAG Coverage

| Principle | Criteria Tested |
|---|---|
| Perceivable | 1.1.1 · 1.3.1 · 1.4.1 · 1.4.3 · 1.4.4 · 1.4.10 |
| Operable | 2.1.1 · 2.1.2 · 2.4.2 · 2.4.3 · 2.4.4 · 2.4.7 |
| Understandable | 3.1.1 · 3.3.1 · 3.3.2 · 3.3.3 |
| Robust | 4.1.2 |

Approximately **85–90% of WCAG 2.1 Level AA** success criteria are covered programmatically. Tests that require human judgment (e.g. captions on live video, cognitive load assessment) are out of scope.

---

## Built With

- [Allen AI OLMo2](https://allenai.org/olmo) — open-source LLM for narrative generation
- [Allen AI Molmo2](https://allenai.org/molmo) — open-source VLM for visual grounding
- [Playwright](https://playwright.dev) — headless browser automation
- [FastAPI](https://fastapi.tiangolo.com) — async Python API
- [Modal](https://modal.com) — serverless GPU deployment
- [Next.js](https://nextjs.org) — React frontend
- [Vercel](https://vercel.com) — frontend hosting
