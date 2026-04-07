"""
WCAG Testing Tool — FastAPI Backend
Manages test runs, streams live progress via WebSocket, serves reports.
"""

import asyncio
import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from playwright.async_api import async_playwright

from wcag_agent import WCAGAgent, Molmo2Pointer
from tests import (
    KeyboardNavTest,
    ZoomTest,
    ColorBlindnessTest,
    FocusIndicatorTest,
    FormErrorTest,
    PageStructureTest,
)
from report_generator import generate_report

# ── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="WCAG 2.1 Level AA Testing Tool", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOTS_DIR)), name="screenshots")

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def serve_frontend():
    return FileResponse(str(STATIC_DIR / "index.html"))

# ── Globals ───────────────────────────────────────────────────────────────────

_agent: Optional[WCAGAgent] = None
_pointer: Optional[Molmo2Pointer] = None
_runs: dict[str, dict] = {}  # run_id → run state

TEST_MAP = {
    "keyboard_nav": KeyboardNavTest,
    "zoom": ZoomTest,
    "color_blindness": ColorBlindnessTest,
    "focus_indicator": FocusIndicatorTest,
    "form_errors": FormErrorTest,
    "page_structure": PageStructureTest,
}

# ── Schema ────────────────────────────────────────────────────────────────────

class StartTestRequest(BaseModel):
    url: str
    tests: list[str]
    task: str = "Navigate and use the main features of this website"
    use_quantization: bool = False


class StartTestResponse(BaseModel):
    run_id: str
    message: str


# ── Lifecycle ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    # Agent is loaded lazily on first test run (model download takes time)
    pass


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": _agent is not None}


@app.post("/api/run", response_model=StartTestResponse)
async def start_run(req: StartTestRequest):
    unknown = [t for t in req.tests if t not in TEST_MAP]
    if unknown:
        raise HTTPException(400, f"Unknown test(s): {unknown}. Valid: {list(TEST_MAP)}")

    run_id = str(uuid.uuid4())
    _runs[run_id] = {
        "run_id": run_id,
        "url": req.url,
        "tests": req.tests,
        "task": req.task,
        "status": "queued",
        "results": [],
        "created_at": datetime.utcnow().isoformat(),
        "use_quantization": req.use_quantization,
    }
    return StartTestResponse(run_id=run_id, message="Run queued. Connect via WebSocket to start.")


@app.get("/api/run/{run_id}")
async def get_run(run_id: str):
    if run_id not in _runs:
        raise HTTPException(404, "Run not found")
    run = _runs[run_id]
    if run["status"] == "complete":
        run["report"] = generate_report(run)
    return run


@app.get("/api/runs")
async def list_runs():
    return [
        {
            "run_id": r["run_id"],
            "url": r["url"],
            "status": r["status"],
            "created_at": r["created_at"],
            "result_count": len(r["results"]),
        }
        for r in _runs.values()
    ]


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/{run_id}")
async def websocket_run(ws: WebSocket, run_id: str):
    await ws.accept()

    if run_id not in _runs:
        await ws.send_json({"type": "error", "message": "Run not found"})
        await ws.close()
        return

    run = _runs[run_id]

    if run["status"] not in ("queued", "error"):
        await ws.send_json({"type": "error", "message": f"Run is already {run['status']}"})
        await ws.close()
        return

    run["status"] = "running"

    async def send(msg: dict):
        try:
            await ws.send_json(msg)
        except Exception:
            pass

    try:
        global _agent, _pointer
        if _agent is None:
            await send({"type": "status", "message": "Loading OLMo2-7B-Instruct (narrative)..."})
            _agent = await asyncio.get_event_loop().run_in_executor(
                None, lambda: WCAGAgent(use_quantization=run["use_quantization"])
            )
        if _pointer is None:
            await send({"type": "status", "message": "Loading Molmo2-4B (visual pointer)..."})
            try:
                _pointer = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: Molmo2Pointer(use_quantization=run["use_quantization"])
                )
            except Exception as e:
                import traceback
                print(f"[Molmo2] LOAD ERROR: {e}\n{traceback.format_exc()}")
                await send({"type": "status", "message": f"Molmo2 pointer unavailable ({e}) — running CSS-only mode."})
                _pointer = None
        await send({"type": "status", "message": "Models ready. Launching browser..."})

        run_dir = SCREENSHOTS_DIR / run_id
        run_dir.mkdir(exist_ok=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 720})

            await send({"type": "status", "message": f"Navigating to {run['url']}..."})
            try:
                await page.goto(run["url"], wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)  # let JS-heavy pages settle
            except Exception as e:
                await send({"type": "error", "message": f"Failed to load URL: {e}"})
                run["status"] = "error"
                await browser.close()
                return

            await send({"type": "status", "message": "Page loaded. Starting tests..."})

            tests_to_run = run["tests"]
            for i, test_id in enumerate(tests_to_run):
                test_cls = TEST_MAP[test_id]
                # Pass Molmo2 pointer only to focus_indicator (the test that uses it)
                test = test_cls(
                    agent=_agent,
                    run_dir=run_dir,
                    pointer=_pointer if test_id == "focus_indicator" else None,
                )

                await send({
                    "type": "test_start",
                    "test": test_id,
                    "test_name": test.TEST_NAME,
                    "index": i,
                    "total": len(tests_to_run),
                })

                # Navigate back to target URL before each test
                try:
                    await page.goto(run["url"], wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(2)
                except Exception:
                    pass

                async for event in test.run(page, run["task"]):
                    await send(event)
                    if event["type"] == "result":
                        run["results"].append(dict(event["data"]))

                await send({"type": "test_complete", "test": test_id})

            await browser.close()

        run["status"] = "complete"
        run["completed_at"] = datetime.utcnow().isoformat()

        await send({"type": "status", "message": "Generating accessibility narrative with OLMo2..."})
        narrative = await _agent.generate_narrative(run["results"], run["url"])
        run["narrative"] = narrative

        report = generate_report(run)
        run["report"] = report

        # Strip base64 screenshots before sending over WebSocket —
        # they're already in the individual `result` events and can push
        # the payload over the 1MB WS frame limit on screenshot-heavy runs.
        def _strip_b64(obj):
            if isinstance(obj, dict):
                return {k: _strip_b64(v) for k, v in obj.items() if k != "screenshot_b64"}
            if isinstance(obj, list):
                return [_strip_b64(i) for i in obj]
            return obj

        await send({"type": "done", "run_id": run_id, "report": _strip_b64(report)})

    except WebSocketDisconnect:
        run["status"] = "disconnected"
    except Exception as e:
        run["status"] = "error"
        run["error"] = str(e)
        try:
            await send({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
