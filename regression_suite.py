#!/usr/bin/env python3
"""
PointCheck Regression Suite
============================
Runs a fixed set of test cases against the staging (or prod) backend and
asserts known expected outcomes. All cases run concurrently.

Test cases
----------
  W3C WAI BAD demo  — ground-truth broken page; must produce failures
  discord.com        — must return page_error (bot block / robots.txt)
  medium.com         — must return page_error (bot block / robots.txt)

Usage
-----
  python regression_suite.py              # staging (default)
  python regression_suite.py --prod       # production

Exit codes
----------
  0  all assertions passed
  1  one or more assertions failed
"""

import argparse
import asyncio
import json
import sys
import time
import urllib.request

import websockets

# ── Environment ───────────────────────────────────────────────────────────────

STAGING_URL = "https://brendanworks-staging--wcag-tester-web.modal.run"
PROD_URL    = "https://brendanworks--wcag-tester-web.modal.run"

# ── Test case definitions ─────────────────────────────────────────────────────

CASES = [
    {
        # W3C WAI BAD site returns 403 to Modal's datacenter IPs.
        # GDS Audit page (GitHub Pages) has no IP blocking and contains
        # every common accessibility failure by design — used as ground truth.
        "label":       "GDS Accessibility Audit page (ground-truth broken page)",
        "url":         "https://alphagov.github.io/accessibility-tool-audit/test-cases.html",
        "tests":       ["keyboard_nav", "color_blindness", "focus_indicator",
                        "form_errors", "page_structure"],
        "wcag":        "2.1",
        "assertions": [
            # Must reach the page — no bot block
            ("no_page_error",   "page_error event must NOT fire"),
            # Must actually scan at least 1 page
            ("pages_scanned",   "pages_scanned must be >= 1"),
            # Known broken page: at least one test must fail
            ("has_failures",    "at least one test must be FAIL (known broken page)"),
            # Narrative must be generated (OLMo-3 runs)
            ("has_narrative",   "OLMo-3 narrative must be present"),
        ],
    },
    {
        # discord.com has a publicly accessible robots.txt that does not
        # explicitly disallow our crawl path.  The old stdlib RobotFileParser
        # was falsely blocking it (disallow_all on a non-200 response).  This
        # case verifies that fix: the scan must NOT be blocked by a robots.txt
        # false positive.  A CAPTCHA block mid-scan is still fine (page_error
        # may or may not fire depending on their bot-detection), but the key
        # assertion is that pages_scanned >= 1 — we got past robots.txt.
        "label":   "discord.com (robots.txt false-positive regression)",
        "url":     "https://discord.com",
        "tests":   ["page_structure"],
        "wcag":    "2.1",
        "assertions": [
            # Must NOT be blocked at the robots.txt stage — page must be reached
            ("pages_scanned", "pages_scanned must be >= 1 (no false-positive robots.txt block)"),
        ],
    },
    {
        "label":   "medium.com (bot-blocked / robots.txt)",
        "url":     "https://medium.com",
        "tests":   ["page_structure"],
        "wcag":    "2.1",
        "assertions": [
            ("page_error_fired", "page_error event must fire"),
            ("zero_pages",       "pages_scanned must be 0"),
        ],
    },
]

# ── HTTP helper ───────────────────────────────────────────────────────────────

def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

# ── Single-case runner ────────────────────────────────────────────────────────

async def run_case(base_url: str, case: dict) -> dict:
    """Run one test case, collect events, return result dict."""
    label = case["label"]
    ws_base = base_url.replace("https://", "wss://")

    # Kick off scan
    resp = post_json(
        f"{base_url}/api/run",
        {
            "url":          case["url"],
            "tests":        case["tests"],
            "task":         "Navigate and use the main features of this website",
            "wcag_version": case["wcag"],
        },
    )
    run_id = resp.get("run_id") or resp.get("job_id")
    if not run_id:
        return {"label": label, "error": f"No run_id in response: {resp}", "events": []}

    # Stream WebSocket
    ws_url = f"{ws_base}/ws/{run_id}"
    events       = []
    page_errors  = []
    report       = {}
    terminal_event = None   # the event type that ended the loop
    t0 = time.time()

    try:
        async with websockets.connect(ws_url, open_timeout=30, ping_timeout=60) as ws:
            while True:
                try:
                    # 480 s per-message timeout — model loading takes ~90 s and
                    # keepalives fire every 20 s, so this should never be hit under
                    # normal conditions.  It's a safety net for hung containers.
                    raw = await asyncio.wait_for(ws.recv(), timeout=480)
                except asyncio.TimeoutError:
                    events.append({"type": "timeout"})
                    terminal_event = {"type": "timeout"}
                    break
                msg = json.loads(raw)
                events.append(msg)

                if msg.get("type") == "page_error":
                    page_errors.append(msg.get("error") or msg.get("message", ""))

                if msg.get("type") in ("done", "error"):
                    report = msg.get("report", {})
                    terminal_event = msg
                    break
    except Exception as exc:
        return {"label": label, "error": str(exc), "events": events}

    return {
        "label":          label,
        "elapsed":        round(time.time() - t0),
        "events":         events,
        "page_errors":    page_errors,
        "report":         report,
        "terminal_event": terminal_event,
    }

# ── Assertion evaluator ───────────────────────────────────────────────────────

def evaluate(case: dict, result: dict) -> list[dict]:
    """Return list of {assertion, description, passed, detail}."""
    outcomes = []
    report      = result.get("report", {})
    page_errors = result.get("page_errors", [])
    summary     = report.get("summary", {})
    pages_scanned = report.get("pages_scanned", 0)
    narrative   = report.get("narrative", "") or ""
    failed      = summary.get("failed", 0)
    passed      = summary.get("passed", 0)

    for assertion, description in case["assertions"]:
        detail = ""
        if assertion == "no_page_error":
            ok = len(page_errors) == 0
            detail = f"got page_error: {page_errors[0][:80]}" if page_errors else ""
        elif assertion == "page_error_fired":
            ok = len(page_errors) > 0
            detail = page_errors[0][:80] if page_errors else "no page_error received"
        elif assertion == "pages_scanned":
            ok = pages_scanned >= 1
            detail = f"pages_scanned={pages_scanned}"
        elif assertion == "zero_pages":
            ok = pages_scanned == 0
            detail = f"pages_scanned={pages_scanned}"
        elif assertion == "has_failures":
            ok = failed >= 1
            detail = f"passed={passed} failed={failed}"
        elif assertion == "has_narrative":
            ok = len(narrative) > 50
            detail = f"narrative length={len(narrative)}"
        else:
            ok = False
            detail = f"unknown assertion: {assertion}"

        outcomes.append({
            "assertion":   assertion,
            "description": description,
            "passed":      ok,
            "detail":      detail,
        })
    return outcomes

# ── Main ─────────────────────────────────────────────────────────────────────

async def main(base_url: str):
    print(f"\n{'═'*64}")
    print(f"  PointCheck Regression Suite")
    print(f"  Backend : {base_url}")
    print(f"  Cases   : {len(CASES)}")
    print(f"{'═'*64}\n")

    # Run cases SEQUENTIALLY — each scan needs the full A100 (40 GB VRAM) to
    # itself.  Running concurrently causes 3 × 16 GB model loads → OOM on the
    # 40 GB GPU, producing silent "error" events instead of real scan results.
    # Sequential run takes ~450 s total (3 × ~150 s) which is acceptable for CI.
    results = []
    for case in CASES:
        try:
            result = await run_case(base_url, case)
        except Exception as exc:
            result = exc
        results.append(result)

    all_passed = True

    for case, result in zip(CASES, results):
        label = case["label"]
        print(f"\n── {label}")

        if isinstance(result, Exception):
            print(f"   ✗ EXCEPTION: {result}")
            all_passed = False
            continue

        if result.get("error"):
            print(f"   ✗ ERROR: {result['error']}")
            all_passed = False
            continue

        print(f"   elapsed: {result.get('elapsed', '?')}s")

        # Show what event ended the WS loop — critical for diagnosing
        # "error" vs "done" vs "timeout" termination
        te = result.get("terminal_event") or {}
        te_type = te.get("type", "none")
        if te_type == "error":
            print(f"   ⚠️  TERMINAL EVENT: error — {te.get('message','')[:100]}")
        elif te_type == "timeout":
            print(f"   ⚠️  TERMINAL EVENT: timeout (>360s between messages)")
        elif te_type == "done":
            print(f"   ✓  TERMINAL EVENT: done")
        else:
            print(f"   ?  TERMINAL EVENT: {te_type}")

        # Show event type distribution for any failed assertions
        type_counts: dict[str, int] = {}
        for ev in result.get("events", []):
            t = ev.get("type", "?")
            type_counts[t] = type_counts.get(t, 0) + 1
        print(f"   events: {dict(sorted(type_counts.items()))}")

        outcomes = evaluate(case, result)
        for o in outcomes:
            icon = "✓" if o["passed"] else "✗"
            line = f"   {icon} {o['description']}"
            if o["detail"]:
                line += f"  [{o['detail']}]"
            print(line)
            if not o["passed"]:
                all_passed = False

    print(f"\n{'═'*64}")
    if all_passed:
        print("  ✓  ALL ASSERTIONS PASSED")
    else:
        print("  ✗  ONE OR MORE ASSERTIONS FAILED")
    print(f"{'═'*64}\n")

    return 0 if all_passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", action="store_true", help="Run against production")
    args = parser.parse_args()
    base = PROD_URL if args.prod else STAGING_URL
    sys.exit(asyncio.run(main(base)))
