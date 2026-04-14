"""
E2E staging test — POST /api/run → stream WebSocket → report results.
Usage:  python staging_e2e_test.py [url_to_scan]
"""
import asyncio
import json
import sys
import time
import urllib.request
import urllib.parse

import websockets

STAGING_BASE = "https://brendanworks-staging--wcag-tester-web.modal.run"
TEST_URL      = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"

# ── helpers ────────────────────────────────────────────────────────────────────

def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


# ── main ───────────────────────────────────────────────────────────────────────

async def run_e2e():
    print(f"\n{'='*60}")
    print(f"  WCAG Staging E2E Test")
    print(f"  Staging backend : {STAGING_BASE}")
    print(f"  Scanning URL    : {TEST_URL}")
    print(f"{'='*60}\n")

    # 1. Health check — Modal cold-start can take 60+ seconds on first hit
    print("▶ Health check (warming container, may take ~60s)...", flush=True)
    health = None
    for attempt in range(8):
        try:
            health_req = urllib.request.Request(f"{STAGING_BASE}/health", method="GET")
            with urllib.request.urlopen(health_req, timeout=30) as r:
                health = json.loads(r.read())
            break
        except Exception as exc:
            wait = 15 * (attempt + 1)
            print(f"  attempt {attempt+1}: {exc} — retrying in {wait}s...", flush=True)
            await asyncio.sleep(wait)
    if health is None:
        print("❌ Health check failed after all retries.")
        return
    print(f"  ✓  {health}")

    # 2. Kick off scan
    print(f"\n▶ Starting scan of {TEST_URL}...", flush=True)
    t0 = time.time()
    resp = post_json(f"{STAGING_BASE}/api/run", {"url": TEST_URL, "pages": 1})
    # /api/run (legacy shim) returns { run_id, message }
    # /api/crawl returns { job_id, message }
    job_id = resp.get("job_id") or resp.get("run_id") or resp.get("id")
    print(f"  job_id = {job_id}")
    if not job_id:
        print(f"ERROR: no job_id in response: {resp}")
        return

    # 3. WebSocket stream
    ws_url = f"{STAGING_BASE.replace('https://', 'wss://')}/ws/crawl/{job_id}"
    print(f"\n▶ Connecting to WebSocket: {ws_url}\n")

    results_received = []
    final_report     = None
    narrative        = None

    try:
        async with websockets.connect(ws_url, open_timeout=30, ping_timeout=60) as ws:
            print("  ✓ Connected\n")
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=300)
                except asyncio.TimeoutError:
                    print("\n⚠️  No message for 5 min — WebSocket timeout.")
                    break

                try:
                    msg = json.loads(raw)
                except Exception:
                    print(f"  [raw] {raw[:200]}")
                    continue

                status  = msg.get("status", "")
                message = msg.get("message", "")
                mtype   = msg.get("type", "")

                # Progress messages
                if status == "progress":
                    print(f"  ⏳ {message}")
                    continue

                # Test result
                if status == "result" or mtype == "result":
                    result = msg.get("result", msg)
                    test_name = result.get("test_name", result.get("test_id", "?"))
                    outcome   = result.get("result", "?")
                    icon = {"pass": "✅", "fail": "❌", "warning": "⚠️"}.get(outcome, "❓")
                    print(f"\n  {icon} {test_name}: {outcome}")
                    if result.get("failure_reason"):
                        print(f"     Reason: {result['failure_reason'][:120]}")
                    if result.get("molmo_analysis") and result["molmo_analysis"] not in ("[not run]", "", None):
                        print(f"     MolmoWeb: {str(result['molmo_analysis'])[:120]}")
                    results_received.append(result)
                    continue

                # Final report / done
                if status in ("done", "complete", "final") or mtype in ("done", "complete", "final", "report"):
                    print(f"\n  ✓ Scan complete message received")
                    final_report = msg
                    narrative = (
                        msg.get("narrative")
                        or msg.get("report", {}).get("narrative")
                        or msg.get("summary")
                    )
                    break

                # Error
                if status == "error":
                    print(f"\n  ❌ Server error: {message}")
                    break

                # Catch-all — print full JSON for anything we don't recognise
                print(f"  [msg] {json.dumps(msg)[:300]}")

    except Exception as e:
        print(f"\n❌ WebSocket error: {e}")
        import traceback; traceback.print_exc()

    elapsed = time.time() - t0

    # 4. Summary
    print(f"\n{'='*60}")
    print(f"  RESULTS SUMMARY  ({elapsed:.0f}s)")
    print(f"{'='*60}")
    print(f"  Tests received : {len(results_received)}")
    passes   = sum(1 for r in results_received if r.get("result") == "pass")
    fails    = sum(1 for r in results_received if r.get("result") == "fail")
    warnings = sum(1 for r in results_received if r.get("result") == "warning")
    print(f"  Pass/Fail/Warn : {passes} / {fails} / {warnings}")

    if narrative:
        print(f"\n  OLMo3 Narrative ({len(narrative)} chars):")
        print(f"  {'─'*55}")
        # Print wrapped
        words = narrative.split()
        line  = "  "
        for w in words:
            if len(line) + len(w) > 72:
                print(line)
                line = "  " + w + " "
            else:
                line += w + " "
        if line.strip():
            print(line)
    else:
        print("\n  ⚠️  No OLMo3 narrative in final message")
        if final_report:
            print(f"  Final report keys: {list(final_report.keys())}")

    print(f"\n{'='*60}\n")

    # Key checks
    print("KEY CHECKS:")
    if passes + fails + warnings == 0:
        print("  ❌ No test results received — WebSocket may have dropped")
    else:
        print(f"  ✅ Received {len(results_received)} test result(s)")

    molmo_worked = any(
        r.get("molmo_analysis") and r["molmo_analysis"] not in ("[not run]", "", None)
        for r in results_received
    )
    print(f"  {'✅' if molmo_worked else '⚠️ '} MolmoWeb analysis {'present' if molmo_worked else 'not seen in any result'}")
    print(f"  {'✅' if narrative else '❌'} OLMo3 narrative {'generated' if narrative else 'MISSING'}")
    print()


if __name__ == "__main__":
    asyncio.run(run_e2e())
