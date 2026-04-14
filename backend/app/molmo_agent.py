"""
MolmoWeb-8B browser action agent loop.

Implements the agentic use of MolmoWeb that the paper describes:
  screenshot → think → decide action → Playwright executes → repeat

Used by WCAG checks to discover and test interactive UI states that
deterministic Playwright scripts cannot reach:
  • Dropdown menus opened by clicking hamburger / nav toggles
  • Modal dialogs triggered by form submit or button clicks
  • Accordion / tab panel content hidden behind interactions
  • Video player controls and caption toggles

MolmoWeb action output format (from MolmoWeb paper, AI2 April 2026):
  {"thought": "<reasoning>", "action": "mouse_click(45.2, 23.1)"}

  x, y coordinates are in [0, 100] normalized viewport space.

Full action space:
  mouse_click(x, y)
  mouse_scroll(x, y, "up"|"down"|"left"|"right", amount)
  key_press("Tab"|"Enter"|"Escape"|...)
  type_text("text")
  done("reason")
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from PIL import Image
from playwright.async_api import Page

from app.models.molmo2 import MolmoWebAnalyzer


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class AgentStep:
    step: int
    thought: str
    raw_output: str
    action: str
    action_type: str   # click | scroll | key | type | done | unknown
    executed: bool = False
    error: Optional[str] = None


@dataclass
class AgentRunResult:
    task: str
    steps: list[AgentStep] = field(default_factory=list)
    completed: bool = False
    completion_reason: str = ""
    final_screenshot: Optional[Image.Image] = None

    @property
    def action_summary(self) -> str:
        return "; ".join(
            s.action for s in self.steps if s.executed
        ) or "no actions executed"

    @property
    def thoughts(self) -> list[str]:
        return [s.thought for s in self.steps if s.thought]


# ── Prompt ────────────────────────────────────────────────────────────────────

_AGENT_PROMPT_TEMPLATE = """\
Task: {task}

Previous actions: {history}

Choose ONE action. x and y coordinates are 0-100 (percent of viewport):
  mouse_click(x, y)
  mouse_scroll(x, y, "down"|"up", amount)
  key_press("Tab"|"Enter"|"Escape"|"Space")
  type_text("text")
  done("reason")

Action:"""


# ── Action parsing ────────────────────────────────────────────────────────────

_ACTION_RE = re.compile(
    r'(mouse_click\s*\([^)]+\)'
    r'|mouse_scroll\s*\([^)]+\)'
    r'|key_press\s*\([^)]+\)'
    r'|type_text\s*\([^)]+\)'
    r'|done\s*\([^)]*\))',
    re.IGNORECASE,
)


def _parse_molmo_action(raw: str) -> tuple[str, str]:
    """
    Parse MolmoWeb output into (thought, action_str).

    Handles:
      1. Clean JSON: {"thought": "...", "action": "mouse_click(...)"}
      2. JSON with noise around it
      3. Bare action string (no JSON wrapper)
    """
    raw = raw.strip()

    # Try to find a JSON object containing both keys
    for pattern in (
        r'\{[^{}]*"thought"[^{}]*"action"[^{}]*\}',
        r'\{[^{}]*"action"[^{}]*\}',
    ):
        m = re.search(pattern, raw, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
                thought = str(obj.get("thought", ""))
                action  = str(obj.get("action", "")).strip()
                if action:
                    return thought, action
            except (json.JSONDecodeError, ValueError):
                pass

    # Fallback: find first recognizable action call anywhere in output
    m2 = _ACTION_RE.search(raw)
    if m2:
        return "", m2.group(1)

    # Nothing parseable — stop the loop gracefully
    return raw[:120], 'done("could not parse action from model output")'


def _classify_action(action: str) -> str:
    a = action.lower().lstrip()
    if a.startswith("mouse_click"):   return "click"
    if a.startswith("mouse_scroll"):  return "scroll"
    if a.startswith("key_press"):     return "key"
    if a.startswith("type_text"):     return "type"
    if a.startswith("done"):          return "done"
    return "unknown"


def _extract_args(action: str) -> list[str]:
    """Extract comma-separated args from the parentheses of an action call."""
    m = re.search(r'\(([^)]*)\)', action)
    if not m:
        return []
    raw = m.group(1)
    # Split on commas not inside quotes
    parts = re.split(r',\s*(?=(?:[^"\']*["\'][^"\']*["\'])*[^"\']*$)', raw)
    return [p.strip().strip('"\'') for p in parts if p.strip()]


# ── Action execution ──────────────────────────────────────────────────────────

async def _execute_action(
    page: Page,
    action: str,
    viewport_w: int,
    viewport_h: int,
) -> None:
    """Map a MolmoWeb action string to a Playwright call."""
    action_type = _classify_action(action)
    args = _extract_args(action)

    if action_type == "click":
        if len(args) >= 2:
            try:
                nx, ny = float(args[0]), float(args[1])
                px = (nx / 100.0) * viewport_w
                py = (ny / 100.0) * viewport_h
                await page.mouse.click(px, py)
            except ValueError:
                pass

    elif action_type == "scroll":
        if len(args) >= 3:
            try:
                nx, ny = float(args[0]), float(args[1])
                direction = args[2].lower().strip('"\'')
                amount = float(args[3]) if len(args) > 3 else 3.0
                px = (nx / 100.0) * viewport_w
                py = (ny / 100.0) * viewport_h
                scroll_px = min(amount, 10) * 120  # ~120px per line
                dx = dy = 0.0
                if direction == "down":   dy =  scroll_px
                elif direction == "up":   dy = -scroll_px
                elif direction == "right": dx =  scroll_px
                elif direction == "left":  dx = -scroll_px
                await page.mouse.move(px, py)
                await page.mouse.wheel(dx, dy)
            except ValueError:
                pass

    elif action_type == "key":
        if args:
            # Normalize common key names
            key = args[0].strip('"\'')
            key_map = {
                "tab": "Tab", "enter": "Enter", "return": "Enter",
                "escape": "Escape", "esc": "Escape", "space": "Space",
                "arrowdown": "ArrowDown", "arrowup": "ArrowUp",
                "arrowleft": "ArrowLeft", "arrowright": "ArrowRight",
            }
            key = key_map.get(key.lower(), key)
            await page.keyboard.press(key)

    elif action_type == "type":
        if args:
            await page.keyboard.type(args[0])

    # "done" and "unknown" — nothing to execute


# ── Agent loop ────────────────────────────────────────────────────────────────

class MolmoWebAgentLoop:
    """
    Drives MolmoWeb-8B as an action policy agent inside a Playwright browser.

    This is the "agentic" use of MolmoWeb — the model decides what to interact
    with on each step based on the current viewport screenshot. Playwright then
    executes the physical action.

    Design constraints:
    - Only used for within-page interactive testing, NOT for BFS navigation.
      Playwright remains in charge of crawl-level navigation for reliability.
    - Max steps is intentionally low (default 8) — we want focused interaction,
      not open-ended browsing.
    - All MolmoWeb errors are caught; the loop degrades gracefully.
    - TOTAL_TIMEOUT caps the entire loop so a slow container cannot consume
      the scan budget (900s Modal timeout) with a single runaway agent call.

    Typical usage in a WCAG check:
        agent = MolmoWebAgentLoop(self.analyzer, max_steps=5)
        result = await agent.run(page, "Find and activate the skip navigation link.")
        yield self._progress(f"Agent took {len(result.steps)} action(s): {result.action_summary}")
    """

    INFERENCE_TIMEOUT = 45.0   # seconds per MolmoWeb inference call
    TOTAL_TIMEOUT     = 240.0  # seconds for the entire agent loop (8 steps × 30s avg)

    def __init__(self, analyzer: MolmoWebAnalyzer, max_steps: int = 8):
        self.analyzer  = analyzer
        self.max_steps = max_steps

    async def run(
        self,
        page: Page,
        task: str,
        stop_keywords: list[str] | None = None,
        progress_cb: "Optional[Callable[[str], None]]" = None,
        total_timeout: float | None = None,
    ) -> AgentRunResult:
        """
        Execute the agent loop for `task`.

        Args:
            page:          Playwright page (already navigated to target URL).
            task:          Natural-language task description.
            stop_keywords: If any of these appear in the page text, stop early.
            progress_cb:   Optional sync callback(message: str) called after
                           each step so callers can yield WS progress events.
            total_timeout: Max wall-clock seconds for the entire loop.
                           Defaults to TOTAL_TIMEOUT (240s). Pass None to disable.

        Returns:
            AgentRunResult with all steps + final screenshot.
            Never raises — all errors are captured in step.error.
        """
        timeout_s = total_timeout if total_timeout is not None else self.TOTAL_TIMEOUT
        try:
            return await asyncio.wait_for(
                self._run_inner(page, task, stop_keywords, progress_cb),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            tag = f"[MolmoAgent task={task[:40]!r}]"
            msg = f"{tag} total timeout after {timeout_s:.0f}s — returning partial result"
            print(msg)
            if progress_cb:
                progress_cb(msg)
            # Return a partial result so callers still get whatever ran
            result = AgentRunResult(task=task)
            result.completion_reason = f"total timeout ({timeout_s:.0f}s)"
            try:
                result.final_screenshot = await self.analyzer.screenshot_to_image(page)
            except Exception:
                pass
            return result

    async def _run_inner(
        self,
        page: Page,
        task: str,
        stop_keywords: list[str] | None,
        progress_cb: "Optional[Callable[[str], None]]",
    ) -> AgentRunResult:
        """Inner loop — wrapped by run() with a total timeout."""
        tag = f"[MolmoAgent task={task[:40]!r}]"
        print(f"{tag} starting (max_steps={self.max_steps})")

        result = AgentRunResult(task=task)
        history: list[str] = []

        for step_num in range(1, self.max_steps + 1):
            screenshot = await self.analyzer.screenshot_to_image(page)
            w, h = screenshot.size

            history_text = (
                ", ".join(history[-4:]) if history else "none yet"
            )
            prompt = _AGENT_PROMPT_TEMPLATE.format(
                task=task,
                history=history_text,
            )

            # --- MolmoWeb inference (use analyze_raw — agent prompt must not be
            #     wrapped in the QA "accessibility expert" framing that analyze() adds) ---
            try:
                raw = await asyncio.wait_for(
                    self.analyzer.analyze_raw(screenshot, prompt, max_new_tokens=80),
                    timeout=self.INFERENCE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                msg = f"{tag} step {step_num}: inference timed out ({self.INFERENCE_TIMEOUT:.0f}s)"
                print(msg)
                if progress_cb: progress_cb(msg)
                result.completion_reason = "inference timed out"
                break
            except Exception as e:
                msg = f"{tag} step {step_num}: inference error: {e}"
                print(msg)
                if progress_cb: progress_cb(msg)
                result.completion_reason = f"inference error: {e}"
                break

            thought, action_str = _parse_molmo_action(raw)
            action_type = _classify_action(action_str)

            step = AgentStep(
                step=step_num,
                thought=thought,
                raw_output=raw[:300],
                action=action_str,
                action_type=action_type,
            )
            history.append(action_str)

            # Log every step — visible in Modal logs and WS progress stream
            step_msg = (
                f"[AGENT step {step_num}/{self.max_steps}] "
                f"thought: {thought[:80] or '—'} | action: {action_str}"
            )
            print(f"{tag} {step_msg}")
            if progress_cb: progress_cb(step_msg)

            # Stop conditions: done/unparseable
            if action_type in ("done", "unknown"):
                step.executed = True
                result.steps.append(step)
                result.completed = True
                result.completion_reason = action_str
                done_msg = f"[AGENT done] {action_str}"
                print(f"{tag} {done_msg}")
                if progress_cb: progress_cb(done_msg)
                break

            # Execute the action via Playwright
            try:
                await _execute_action(page, action_str, w, h)
                await asyncio.sleep(0.6)  # let DOM settle
                step.executed = True
            except Exception as e:
                step.error = str(e)
                err_msg = f"[AGENT step {step_num} execute error] {e}"
                print(f"{tag} {err_msg}")
                if progress_cb: progress_cb(err_msg)

            result.steps.append(step)

            # Check stop keywords
            if stop_keywords:
                try:
                    page_text = await page.evaluate(
                        "() => document.body.innerText.slice(0, 3000)"
                    )
                    if any(kw.lower() in page_text.lower() for kw in stop_keywords):
                        result.completed = True
                        result.completion_reason = "stop keyword matched"
                        break
                except Exception:
                    pass

        summary = (
            f"{tag} finished: {len(result.steps)} step(s) executed, "
            f"reason={result.completion_reason or 'max_steps reached'}"
        )
        print(summary)
        if progress_cb: progress_cb(summary)

        result.final_screenshot = await self.analyzer.screenshot_to_image(page)
        return result
