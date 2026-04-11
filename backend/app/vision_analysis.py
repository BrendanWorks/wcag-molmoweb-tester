"""
Holistic vision analysis module for MolmoAccess Agent.

Public API
──────────
    await analyze_screenshot_with_molmo2(image_bytes, wcag_version, analyzer)
        → list[IssueDict]          # one dict per detected WCAG violation

    await analyze_video_frame(frame_bytes, analyzer)
        → VideoFindingsDict        # video-specific accessibility findings

Both functions are async and GPU-bound; they run Molmo2 inference in a thread
executor so they never block the event loop.

Design notes
────────────
MolmoWeb-8B is a vision-language model trained on 2.2M screenshot QA pairs and
100K+ web-task trajectories. It understands web UI far better than a generic VLM.

We use TWO prompt passes per page:
  Pass 1  — "holistic" prompt: all 7 WCAG categories in one call.
            Cheaper than 7 separate calls; Molmo2 can identify issues across
            the whole viewport in a single forward pass.
  Pass 2  — "deep-dive" prompt per video element (if any detected).
            Each <video> frame gets a focused captioning + controls check.

JSON output is parsed with multi-stage fallback:
  Stage 1 — json.loads on the raw output
  Stage 2 — extract JSON block from markdown fences
  Stage 3 — regex extraction of individual issue objects
  Stage 4 — return empty list (never crash the crawl)

Output shape (IssueDict) is backward-compatible with TestResult.__dict__ so
`build_page_report()` can consume it without modification.
"""

from __future__ import annotations

import asyncio
import json
import re
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from PIL import Image

if TYPE_CHECKING:
    from app.models.molmo2 import MolmoWebAnalyzer


# ── Type alias ────────────────────────────────────────────────────────────────

IssueDict = dict[str, Any]   # shape mirrors TestResult.__dict__


# ── WCAG 2.2 system + user prompts ────────────────────────────────────────────
#
# These prompts are the primary driver of analysis quality.
# Design principles:
#   1. Role-prime first — establish expert identity before any instructions
#   2. Enumerate criteria explicitly — prevents hallucinated criterion numbers
#   3. JSON schema with a single complete example — best few-shot for JSON output
#   4. Hard constraints last — token budget, field values, "only what you see"
#   5. User turn is short — the system turn does all the heavy lifting

_SYSTEM_PROMPT_WCAG22 = """\
You are a senior web accessibility auditor certified in WCAG 2.2 Level AA. \
Your job is to examine a single webpage screenshot and report every \
accessibility violation you can visually confirm.

WCAG 2.2 CRITERIA YOU MUST CHECK
──────────────────────────────────
Category          test_id            Criteria to check
─────────────────────────────────────────────────────────────────────────────
Keyboard nav      keyboard_nav       2.1.1 (keyboard operable), 2.1.2 (no trap),
                                     2.4.1 (skip link at page top), 2.4.3 (focus order)
Resize & reflow   zoom               1.4.4 (text resizable), 1.4.10 (single-column reflow)
Color & contrast  color_blindness    1.4.1 (not color-only), 1.4.3 (4.5:1 text contrast,
                                     3:1 large text / UI components)
Focus visibility  focus_indicator    2.4.7 (visible focus ring / outline on interactive elements)
Form errors       form_errors        3.3.1 (errors identified), 3.3.2 (labels on inputs),
                                     3.3.3 (error suggestions)
Page structure    page_structure     1.1.1 (alt text on images), 1.3.1 (heading hierarchy,
                                     landmarks), 2.4.2 (page title), 2.4.4 (link purpose),
                                     3.1.1 (lang attr), 4.1.1 (no dup IDs), 4.1.2 (ARIA)
Video & motion    video_motion       1.2.2 (captions on video), 2.2.2 (pause/stop controls
                                     on auto-playing content), 2.3.1 (no 3+ flashes/sec)

VISUAL EVIDENCE RULES
─────────────────────
• Report ONLY issues you can VISUALLY CONFIRM from this screenshot.
• Do NOT infer from element types alone (e.g. do not report "no alt text" just
  because you see an <img> tag — report it only if the image appears decorative
  or the caption / surrounding text suggests missing alt).
• For contrast failures: estimate ratios only when the difference is obvious
  (e.g., light grey text on white background). Mark as "warning" when uncertain.
• For focus indicators: only report 2.4.7 if you can see a focused element with
  no visible outline or ring. If no element appears focused, omit this issue.
• For skip links: report 2.4.1 as a warning if no "Skip to content" link is
  visible at the very top of the page and the page has a navigation menu.

SEVERITY DEFINITIONS
────────────────────
critical  — Completely blocks access for one or more disability groups
major     — Significantly impairs access; common disability group affected
minor     — Nuisance or best-practice violation; workaround exists

REQUIRED OUTPUT FORMAT
──────────────────────
Output ONLY the following JSON. No prose before or after.
Return an empty "issues" array if you find no violations.

{
  "issues": [
    {
      "test_id": "page_structure",
      "wcag_criteria": ["1.1.1"],
      "result": "fail",
      "severity": "critical",
      "failure_reason": "Hero image has no alt text and conveys the page topic",
      "recommendation": "Add descriptive alt text, e.g. alt='Team photo at company retreat'",
      "visual_evidence": "Large banner image top-center, no visible caption or surrounding text"
    }
  ],
  "visual_summary": "E-commerce product page. Header nav + hero image + 3-column product grid. No skip link visible."
}

FIELD CONSTRAINTS
─────────────────
test_id        : MUST be one of: keyboard_nav | zoom | color_blindness |
                 focus_indicator | form_errors | page_structure | video_motion
wcag_criteria  : MUST be real WCAG 2.2 criterion numbers from the table above
result         : MUST be "fail" | "warning" | "pass"  (omit "pass" — only report problems)
severity       : MUST be "critical" | "major" | "minor"
failure_reason : ≤ 100 chars, plain English, specific to what you see
recommendation : ≤ 120 chars, actionable fix
visual_evidence: ≤ 120 chars, describes the screenshot element that proves the issue
Maximum 10 issues. Most pages will have 0–5. Quality over quantity.\
"""

_SYSTEM_PROMPT_WCAG21 = _SYSTEM_PROMPT_WCAG22.replace(
    "WCAG 2.2 Level AA", "WCAG 2.1 Level AA"
).replace(
    # Remove 2.2-specific criterion 2.5.8 from the table (not in 2.1)
    "4.1.2 (ARIA)", "4.1.2 (ARIA)\n                                     [Note: 2.5.8 Target Size is WCAG 2.2 only — skip]"
)

_USER_PROMPT_TEMPLATE = """\
Analyze this webpage screenshot for WCAG {wcag_version} Level AA accessibility violations.
Page URL: {page_url}

Focus especially on:
{focus_areas}

Return ONLY the JSON object described in the system prompt.\
"""

_VIDEO_SYSTEM_PROMPT = """\
You are a WCAG 2.2 video accessibility expert. You are looking at a single \
frame captured from a <video> element on a webpage.

Check for:
1. WCAG 1.2.2 — Are closed captions or subtitles visible in this frame?
   Look for: subtitle text overlaid on the video, a CC indicator, or a caption panel below.
2. WCAG 2.2.2 — Does the video player UI (if visible) include pause/stop/play controls?
   Look for: a control bar at the bottom with pause, play, or stop buttons.
3. WCAG 2.3.1 — Does any content in this frame appear to flash rapidly?
   Look for: strobe-like patterns, rapid alternation between high-contrast areas.

Output ONLY this JSON:
{
  "has_captions": true | false | "unknown",
  "has_controls": true | false | "unknown",
  "has_flashing": true | false | "unknown",
  "caption_evidence": "brief description of what you see or 'not visible'",
  "controls_evidence": "brief description of what you see or 'not visible'",
  "issues": [
    {
      "wcag_criterion": "1.2.2",
      "severity": "major",
      "description": "No captions visible in captured frame"
    }
  ]
}
Only include issues you can visually confirm. Return empty "issues" if everything looks fine.\
"""


# ── JSON extraction ────────────────────────────────────────────────────────────

def _extract_json(raw: str) -> dict:
    """
    Multi-stage JSON extraction. Handles:
      - Clean JSON output
      - JSON in ```json ... ``` markdown fences
      - JSON preceded/followed by explanatory text
      - Truncated JSON (Molmo hit token limit mid-object)
    """
    raw = raw.strip()

    # Stage 1: direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Stage 2: extract from markdown code fence
    fence_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Stage 3: find outermost {...} block
    brace_match = re.search(r'(\{.*\})', raw, re.DOTALL)
    if brace_match:
        candidate = brace_match.group(1)
        # Attempt to close truncated JSON by counting braces
        open_b  = candidate.count('{')
        close_b = candidate.count('}')
        if open_b > close_b:
            candidate += '}' * (open_b - close_b)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Stage 4: extract individual issue objects via regex
    issues = []
    for m in re.finditer(
        r'\{\s*"test_id"\s*:.*?"visual_evidence"\s*:\s*"[^"]*"\s*\}',
        raw,
        re.DOTALL,
    ):
        try:
            issues.append(json.loads(m.group(0)))
        except json.JSONDecodeError:
            pass

    if issues:
        return {"issues": issues, "visual_summary": "[partial extraction]"}

    return {"issues": [], "visual_summary": "[parse failed]"}


def _validate_issue(issue: dict) -> bool:
    """Return True if the issue dict has the required fields with valid values."""
    valid_test_ids = {
        "keyboard_nav", "zoom", "color_blindness",
        "focus_indicator", "form_errors", "page_structure", "video_motion",
    }
    valid_results   = {"fail", "warning", "pass"}
    valid_severities = {"critical", "major", "minor"}

    return (
        isinstance(issue.get("test_id"), str) and issue["test_id"] in valid_test_ids
        and isinstance(issue.get("wcag_criteria"), list) and len(issue["wcag_criteria"]) > 0
        and issue.get("result") in valid_results
        and issue.get("severity") in valid_severities
        and isinstance(issue.get("failure_reason"), str)
    )


def _issue_to_result_dict(issue: dict, page_url: str) -> IssueDict:
    """Normalize a validated issue dict to match TestResult.__dict__ shape."""
    return {
        "test_id":        issue["test_id"],
        "test_name":      f"Vision: {issue['test_id'].replace('_', ' ').title()}",
        "result":         issue["result"],
        "wcag_criteria":  issue["wcag_criteria"],
        "severity":       issue["severity"],
        "failure_reason": issue.get("failure_reason", ""),
        "recommendation": issue.get("recommendation", ""),
        "screenshot_path": None,
        "screenshot_b64":  None,
        "details": {
            "source":          "molmo2_vision",
            "visual_evidence": issue.get("visual_evidence", ""),
        },
        "molmo_analysis": issue.get("visual_evidence", ""),
        "page_url":       page_url,
        "timestamp":      "",   # filled in by caller
    }


# ── Build focus areas string for user prompt ──────────────────────────────────

def _focus_areas(page_context: dict) -> str:
    """
    Build a tailored list of focus areas for the user prompt based on
    what the programmatic checks already found (avoids redundant deep-dives).
    """
    existing_failures = page_context.get("existing_failure_test_ids", set())
    hints = page_context.get("hints", [])

    areas = []
    if "page_structure" not in existing_failures:
        areas.append("• Heading hierarchy (h1→h2→h3), alt text on images, link text clarity")
    if "color_blindness" not in existing_failures:
        areas.append("• Text contrast and color-only information encoding")
    if "keyboard_nav" not in existing_failures:
        areas.append("• Skip navigation link at page top")
    if "video_motion" not in existing_failures:
        areas.append("• Video/audio elements and their pause/caption controls")
    if hints:
        areas.extend(f"• {h}" for h in hints)

    return "\n".join(areas) if areas else "• All WCAG 2.2 Level AA categories"


# ── Public API ─────────────────────────────────────────────────────────────────

async def analyze_screenshot_with_molmo2(
    image_bytes: bytes,
    wcag_version: str = "2.2",
    analyzer: Optional["MolmoWebAnalyzer"] = None,
    page_url: str = "",
    page_context: Optional[dict] = None,
) -> list[IssueDict]:
    """
    Run a holistic WCAG analysis pass on a full-page screenshot.

    Args:
        image_bytes:   Raw PNG/JPEG bytes from Playwright page.screenshot().
        wcag_version:  "2.1" or "2.2" — selects the appropriate criterion table.
        analyzer:      MolmoWebAnalyzer singleton. If None, returns [].
        page_url:      Used for context in the user prompt and result stamping.
        page_context:  Optional dict with hints from programmatic checks:
                       { "existing_failure_test_ids": set[str], "hints": list[str] }

    Returns:
        List of IssueDict items, each shaped like TestResult.__dict__.
        Empty list if analysis fails or no issues found.
    """
    if analyzer is None:
        return []

    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    system_prompt = _SYSTEM_PROMPT_WCAG22 if wcag_version == "2.2" else _SYSTEM_PROMPT_WCAG21
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        wcag_version=wcag_version,
        page_url=page_url or "unknown",
        focus_areas=_focus_areas(page_context or {}),
    )

    # Combine system + user into a single turn (Molmo2 has no system-role concept;
    # we inject the system prompt as the beginning of the user message)
    full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"

    raw = await _run_vision_inference(image, full_prompt, analyzer, max_new_tokens=512)
    if not raw:
        return []

    parsed = _extract_json(raw)
    raw_issues = parsed.get("issues", [])

    validated: list[IssueDict] = []
    for issue in raw_issues[:10]:  # hard cap
        if _validate_issue(issue):
            validated.append(_issue_to_result_dict(issue, page_url))

    return validated


async def analyze_video_frame(
    frame_bytes: bytes,
    analyzer: Optional["MolmoWebAnalyzer"] = None,
    page_url: str = "",
) -> dict[str, Any]:
    """
    Analyze a single frame captured from a <video> element.

    Two-pass analysis:
      Pass 1 (QA):      Structured WCAG questions about captions, controls, flashing.
      Pass 2 (pointing): Molmo2 points to caption button + play/pause button in pixel
                         space, giving precise element locations for the eval dataset.

    Returns a dict:
      {
        "has_captions":       bool | "unknown",
        "has_controls":       bool | "unknown",
        "has_flashing":       bool | "unknown",
        "caption_button_xy":  [x, y] px | None,   # Molmo2 pointing result
        "playpause_button_xy":[x, y] px | None,
        "issues":             list[dict],
        "raw_response":       str,
      }
    """
    empty: dict[str, Any] = {
        "has_captions":        "unknown",
        "has_controls":        "unknown",
        "has_flashing":        "unknown",
        "caption_button_xy":   None,
        "playpause_button_xy": None,
        "issues":              [],
        "raw_response":        "",
    }

    if analyzer is None or not frame_bytes:
        return empty

    try:
        image = Image.open(BytesIO(frame_bytes)).convert("RGB")
    except Exception:
        return empty

    # Pass 1: structured QA analysis
    raw = await _run_vision_inference(
        image, _VIDEO_SYSTEM_PROMPT, analyzer, max_new_tokens=256
    )
    if not raw:
        return {**empty, "raw_response": raw}

    parsed = _extract_json(raw)
    result: dict[str, Any] = {
        "has_captions":        parsed.get("has_captions", "unknown"),
        "has_controls":        parsed.get("has_controls", "unknown"),
        "has_flashing":        parsed.get("has_flashing", "unknown"),
        "caption_evidence":    parsed.get("caption_evidence", ""),
        "controls_evidence":   parsed.get("controls_evidence", ""),
        "caption_button_xy":   None,
        "playpause_button_xy": None,
        "issues":              parsed.get("issues", []),
        "raw_response":        raw,
    }

    # Pass 2: pointing — locate caption button and play/pause button in pixel space.
    # This gives the eval dataset precise element coordinates for ground-truth labeling
    # and lets us verify controls are actually reachable (not occluded, not off-screen).
    w, h = image.size

    # Caption / subtitles toggle
    try:
        caption_pt = await asyncio.wait_for(
            analyzer.point_to(
                image,
                "the closed captions or subtitles button in the video player controls",
            ),
            timeout=45.0,
        )
        if caption_pt:
            px, py = caption_pt
            result["caption_button_xy"] = [round(px), round(py)]
            # If we can point to a caption button, record it as evidence
            if result["has_captions"] == "unknown":
                result["has_captions"] = True
    except (asyncio.TimeoutError, Exception):
        pass

    # Play / pause button
    try:
        pp_pt = await asyncio.wait_for(
            analyzer.point_to(
                image,
                "the play or pause button in the video player controls",
            ),
            timeout=45.0,
        )
        if pp_pt:
            px, py = pp_pt
            result["playpause_button_xy"] = [round(px), round(py)]
            # Verify it's within the viewport bounds (not off-screen)
            if not (0 <= px <= w and 0 <= py <= h):
                result["issues"].append({
                    "wcag_criterion": "2.1.1",
                    "severity": "major",
                    "description": (
                        "Play/pause button pointed to outside viewport bounds — "
                        "may not be keyboard-reachable."
                    ),
                })
    except (asyncio.TimeoutError, Exception):
        pass

    # If controls are absent per QA and pointing found nothing, flag 2.1.1
    if result["has_controls"] is False and result["playpause_button_xy"] is None:
        result["issues"].append({
            "wcag_criterion": "2.1.1",
            "severity": "major",
            "description": (
                "Video has no visible player controls. Keyboard users cannot "
                "pause, stop, or control video playback (WCAG 2.1.1, 2.2.2)."
            ),
        })

    return result


# ── Low-level inference helper ────────────────────────────────────────────────

async def _run_vision_inference(
    image: Image.Image,
    prompt: str,
    analyzer: "MolmoWebAnalyzer",
    max_new_tokens: int = 512,
) -> str:
    """
    Run MolmoWeb-8B inference via the analyzer's thread executor.
    Returns the raw decoded string, or "" on error.
    """
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: analyzer._run_inference(image, prompt, max_new_tokens),
            ),
            timeout=90.0,   # holistic analysis can take up to 90s on A10G
        )
    except asyncio.TimeoutError:
        print(f"[vision_analysis] Inference timed out after 90s")
        return ""
    except Exception as e:
        print(f"[vision_analysis] Inference error: {e}")
        return ""


# ── Video frame capture (Playwright helper, used from crawler) ────────────────

async def capture_video_frames(page, run_dir: Path) -> list[tuple[bytes, dict]]:
    """
    Find all <video> elements on the current page, capture frames from each,
    and return a list of (frame_bytes, video_metadata) tuples.

    For each video:
      - Captures 3 frames spaced 200ms apart (at t=1s, 1.2s, 1.4s).
      - Computes pixel-change rate between consecutive frames to estimate
        motion intensity and flag potential photosensitive seizure risk
        (WCAG 2.3.1: no content that flashes more than 3 times per second
        occupying a large area of the screen).
      - Returns the first frame for visual QA; stores motion metadata.

    Metadata dict:
      { "src", "index", "width", "height", "autoplay", "has_controls",
        "has_track", "frame_path",
        "motion_score": float,  # 0.0–1.0, fraction of pixels that changed >10%
        "flicker_risk": bool }  # True if motion_score > 0.3 across 3 frames
    """
    video_infos: list[dict] = await page.evaluate("""() => {
        return Array.from(document.querySelectorAll('video')).map((v, i) => ({
            index:        i,
            src:          v.currentSrc || v.getAttribute('src') || '',
            width:        Math.round(v.getBoundingClientRect().width),
            height:       Math.round(v.getBoundingClientRect().height),
            autoplay:     v.autoplay,
            has_controls: v.controls,
            has_track:    v.querySelectorAll('track[kind="captions"], track[kind="subtitles"]').length > 0,
            visible:      v.getBoundingClientRect().width > 0,
        }));
    }""")

    frames: list[tuple[bytes, dict]] = []
    for info in video_infos:
        if not info.get("visible") or info.get("width", 0) < 10:
            continue
        try:
            video_locator = page.locator("video").nth(info["index"])
            multi_frames: list[bytes] = []

            # Capture 3 frames at 200ms intervals starting at t=1s
            for t_offset in (1.0, 1.2, 1.4):
                await page.evaluate(f"""() => {{
                    const v = document.querySelectorAll('video')[{info['index']}];
                    if (v) {{ try {{ v.currentTime = {t_offset}; }} catch(e) {{}} }}
                }}""")
                await asyncio.sleep(0.25)
                try:
                    fb = await video_locator.screenshot(timeout=5000)
                    multi_frames.append(fb)
                except Exception:
                    break

            if not multi_frames:
                continue

            first_frame = multi_frames[0]

            # Save primary frame for eval dataset
            frame_path = run_dir / f"video_frame_{info['index']}.png"
            frame_path.write_bytes(first_frame)
            info["frame_path"] = str(frame_path)

            # ── Multi-frame flicker / motion analysis ─────────────────────────
            # Compare consecutive frames pixel-by-pixel to estimate motion rate.
            # High pixel-change rate across short intervals → flicker/seizure risk.
            motion_score = 0.0
            flicker_risk = False
            if len(multi_frames) >= 2:
                try:
                    motion_score = _compute_motion_score(multi_frames)
                    # Threshold: >30% pixels changed across 200ms ≈ very rapid motion
                    flicker_risk = motion_score > 0.30
                    if flicker_risk:
                        print(
                            f"[vision_analysis] Video {info['index']}: "
                            f"flicker risk! motion_score={motion_score:.2f}"
                        )
                except Exception as e:
                    print(f"[vision_analysis] Motion score error: {e}")

            info["motion_score"] = round(motion_score, 3)
            info["flicker_risk"] = flicker_risk

            frames.append((first_frame, info))

        except Exception as e:
            print(f"[vision_analysis] Frame capture failed for video {info['index']}: {e}")

    return frames


def _compute_motion_score(frame_bytes_list: list[bytes]) -> float:
    """
    Compute the fraction of pixels that changed significantly between
    consecutive frames.  Returns a value in [0.0, 1.0].

    Uses PIL only (no numpy dependency) — compares grayscale pixel values
    with a threshold of 25/255 (~10%) per channel.
    """
    if len(frame_bytes_list) < 2:
        return 0.0

    total_changed = 0
    total_comparisons = 0

    prev_img = None
    for fb in frame_bytes_list:
        try:
            img = Image.open(BytesIO(fb)).convert("L")  # grayscale
            # Downsample for speed: max 200×150
            img = img.resize((200, 150), Image.BILINEAR)
        except Exception:
            continue

        if prev_img is not None and prev_img.size == img.size:
            prev_pixels = list(prev_img.getdata())
            curr_pixels = list(img.getdata())
            n = len(prev_pixels)
            changed = sum(
                1 for p, c in zip(prev_pixels, curr_pixels) if abs(p - c) > 25
            )
            total_changed += changed
            total_comparisons += n

        prev_img = img

    if total_comparisons == 0:
        return 0.0
    return total_changed / total_comparisons


# ── Merge vision issues into page results ─────────────────────────────────────

def merge_vision_into_results(
    programmatic_results: list[dict],
    vision_issues: list[IssueDict],
    video_findings: list[dict],
) -> list[dict]:
    """
    Merge vision analysis results with programmatic check results.

    Strategy:
    - Programmatic results are authoritative (never downgraded by vision).
    - Vision issues for a test_id that already FAILED are added as detail.
    - Vision issues for a test_id that PASSED programmatically are added as
      new "warning" entries (visual concern the DOM check missed).
    - Video findings that surface new issues are appended to video_motion results.
    """
    prog_by_test_id: dict[str, dict] = {
        r["test_id"]: r for r in programmatic_results
    }

    merged = list(programmatic_results)  # start with programmatic as ground truth

    for vis in vision_issues:
        tid = vis["test_id"]
        existing = prog_by_test_id.get(tid)

        if existing is None:
            # No programmatic result for this test — add the vision finding directly
            merged.append(vis)
        elif existing.get("result") == "pass":
            # Programmatic passed but vision spotted something — add as warning
            vis_copy = dict(vis)
            vis_copy["result"] = "warning"
            vis_copy["failure_reason"] = (
                "[Visual concern — programmatic DOM check passed] "
                + vis_copy.get("failure_reason", "")
            )
            merged.append(vis_copy)
        else:
            # Both agree there's an issue — annotate existing result with vision evidence
            if "details" not in existing or existing["details"] is None:
                existing["details"] = {}
            existing["details"]["vision_evidence"] = vis.get("molmo_analysis", "")
            existing["details"]["vision_recommendation"] = vis.get("recommendation", "")

    # Merge video findings into the video_motion result
    vm_result = prog_by_test_id.get("video_motion")
    for vf in video_findings:
        vf_issues = vf.get("issues", [])
        for vfi in vf_issues:
            # Add as a supplemental video_motion warning if not already captured
            new_issue = {
                "test_id":        "video_motion",
                "test_name":      "Video, Audio & Motion (frame analysis)",
                "result":         "warning",
                "wcag_criteria":  [vfi.get("wcag_criterion", "1.2.2")],
                "severity":       vfi.get("severity", "major"),
                "failure_reason": vfi.get("description", "")[:100],
                "recommendation": "Verify this video meets WCAG 1.2.2 and 2.2.2 requirements.",
                "screenshot_path": None,
                "screenshot_b64":  None,
                "details":         {"source": "video_frame_analysis", "raw": vf.get("raw_response", "")},
                "molmo_analysis":  vf.get("raw_response", ""),
                "page_url":        "",
                "timestamp":       "",
            }
            merged.append(new_issue)

    return merged
