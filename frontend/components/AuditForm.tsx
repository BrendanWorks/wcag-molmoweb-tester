"use client";

import { useState, useRef, useEffect } from "react";
import TestSelector, { TEST_OPTIONS } from "@/components/TestSelector";
import ProgressDisplay from "@/components/ProgressDisplay";
import ResultsDashboard from "@/components/ResultsDashboard";
import { useWcagVersion } from "@/components/WcagVersionProvider";
import { analytics } from "@/lib/analytics";

type Phase = "form" | "running" | "done" | "loading";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");

export default function AuditForm() {
  const [url, setUrl] = useState("");
  const [task, setTask] = useState("Navigate and use the main features of this website");
  const [selectedTests, setSelectedTests] = useState<string[]>(
    TEST_OPTIONS.map((t) => t.id)
  );
const { version: wcagVersion, setVersion: setWcagVersion } = useWcagVersion();
  const [phase, setPhase] = useState<Phase>("form");
  const [events, setEvents] = useState<object[]>([]);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [blockWarning, setBlockWarning] = useState("");
  const [submittedUrl, setSubmittedUrl] = useState("");
  const [showColdStart, setShowColdStart] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const coldStartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Keep a snapshot of settings for retry
  const lastSettingsRef = useRef({ task, selectedTests, wcagVersion });
  // Collect screenshot_b64 from streaming result events (stripped from done report to save WS payload)
  const screenshotMapRef = useRef<Record<string, string>>({});
  // Native DOM refs — read input values directly to bypass React 19 synthetic event issues
  const urlInputRef = useRef<HTMLInputElement | null>(null);
  const taskInputRef = useRef<HTMLInputElement | null>(null);

  // ── Permalink: load report from ?job= URL param on mount ────────────────────
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const jobId = params.get("job");
    if (!jobId) return;

    setPhase("loading");
    fetch(`${API_BASE}/api/crawl/${encodeURIComponent(jobId)}`)
      .then((res) => {
        if (!res.ok) throw new Error(res.status === 404 ? "Report not found — it may have expired." : `Server error ${res.status}`);
        return res.json();
      })
      .then((jobState: Record<string, unknown>) => {
        if (jobState.status !== "complete" || !jobState.report) {
          throw new Error("This report is not yet complete or is no longer available.");
        }
        const r = jobState.report as Record<string, unknown>;
        setReport(r);
        setSubmittedUrl((r.url ?? jobState.url ?? "") as string);
        setPhase("done");
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err));
        setPhase("done");
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    return () => {
      wsRef.current?.close();
      if (coldStartTimerRef.current) clearTimeout(coldStartTimerRef.current);
    };
  }, []);

  // ── Core audit runner (called by submit and retry) ──────────────────────────
  async function runAudit(urlValue: string, settings: {
    task: string;
    selectedTests: string[];
    wcagVersion: "2.1" | "2.2";
  }) {
    wsRef.current?.close();
    if (coldStartTimerRef.current) clearTimeout(coldStartTimerRef.current);

    setSubmittedUrl(urlValue);
    setError("");
    setBlockWarning("");
    setEvents([]);
    setReport(null);
    setShowColdStart(false);
    screenshotMapRef.current = {};
    setPhase("running");

    // Show cold-start notice if no events arrive within 8 s
    coldStartTimerRef.current = setTimeout(() => setShowColdStart(true), 8000);

    function dismissColdStart() {
      if (coldStartTimerRef.current) {
        clearTimeout(coldStartTimerRef.current);
        coldStartTimerRef.current = null;
      }
      setShowColdStart(false);
    }

    try {
      const res = await fetch(`${API_BASE}/api/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: urlValue,
          tests: settings.selectedTests,
          task: settings.task.trim() || "Navigate and use the main features of this website",
wcag_version: settings.wcagVersion,
        }),
      });

      if (!res.ok) {
        dismissColdStart();
        const body = await res.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? `Server error ${res.status}`);
      }

      const { run_id } = (await res.json()) as { run_id: string };
      const ws = new WebSocket(`${WS_BASE}/ws/${run_id}`);
      wsRef.current = ws;

      ws.onmessage = (ev) => {
        dismissColdStart(); // first event = models loaded
        const msg = JSON.parse(ev.data as string) as Record<string, unknown>;
        setEvents((prev) => [...prev, msg]);

        // Collect screenshot_b64 from each result event (stripped from the final report to save WS payload)
        if (msg.type === "result") {
          const data = msg.data as Record<string, unknown> | undefined;
          const testId = (data?.test_id ?? msg.test) as string | undefined;
          const b64 = data?.screenshot_b64 as string | undefined;
          if (testId && b64) screenshotMapRef.current[testId] = b64;
        }

        if (msg.type === "done") {
          // Merge screenshots back into test_summaries before storing the report
          const report = msg.report as Record<string, unknown>;
          const summaries = report?.test_summaries as Array<Record<string, unknown>> | undefined;
          if (summaries) {
            summaries.forEach((ts) => {
              const id = ts.test_id as string;
              if (!ts.screenshot_b64 && screenshotMapRef.current[id]) {
                ts.screenshot_b64 = screenshotMapRef.current[id];
              }
            });
          }
          // If no pages were scanned and no specific warning was set yet,
          // surface a generic "nothing was tested" message
          const pagesScanned = (report.pages_scanned as number) ?? 0;
          if (pagesScanned === 0) {
            setBlockWarning((prev) =>
              prev ||
              "No pages could be scanned. The site may block automated access, require login, or disallow crawling via robots.txt."
            );
          }
          setReport(report);
          setPhase("done");
          ws.close();
          const s = (report.summary as Record<string, number>) ?? {};
          analytics.auditCompleted({
            url: urlValue,
            wcagVersion: settings.wcagVersion,
            passed: s.passed ?? 0,
            failed: s.failed ?? 0,
            warnings: s.warnings ?? 0,
            compliancePct: (report.compliance_percentage as number) ?? 0,
          });
        }
        if (msg.type === "page_error") {
          // Surface blocking reason — scan may still finish with empty results
          setBlockWarning((msg.error ?? msg.message) as string);
        }
        if (msg.type === "error") {
          const errMsg = msg.message as string;
          setError(errMsg);
          setPhase("done");
          ws.close();
          analytics.auditError(urlValue, errMsg);
        }
      };

      ws.onerror = () => {
        dismissColdStart();
        const errMsg = "Connection lost. The server may still be warming up — please try again in a few seconds.";
        setError(errMsg);
        setPhase("done");
        analytics.auditError(urlValue, errMsg);
      };

      ws.onclose = (ev) => {
        dismissColdStart();
        // Only flag as unexpected if we were still waiting for results
        if (!ev.wasClean) {
          setPhase((current) => {
            if (current === "running") {
              setError("Connection to the backend dropped unexpectedly. Please try again.");
              return "done";
            }
            return current;
          });
        }
      };
    } catch (err: unknown) {
      dismissColdStart();
      const errMsg = err instanceof Error ? err.message : String(err);
      setError(errMsg);
      setPhase("done");
      analytics.auditError(urlValue, errMsg);
    }
  }

  // ── Core submit logic (no event dependency) ──────────────────────────────────
  // NOTE: React 19 / Next.js 16 App Router intercepts <form onSubmit> for
  // progressive enhancement, which can prevent e.preventDefault() from working.
  // We bypass this entirely by wiring submission to button onClick + Enter key.
  function doSubmit() {
    // Read directly from DOM refs — bypasses React 19 controlled-input state lag
    const rawUrl  = (urlInputRef.current?.value  ?? url).trim();
    const rawTask = (taskInputRef.current?.value  ?? task).trim();
    if (rawUrl  !== url)  setUrl(rawUrl);
    if (rawTask !== task) setTask(rawTask);

    let urlValue = rawUrl;
    if (!urlValue || selectedTests.length === 0) {
      setError(urlValue ? "Please select at least one test." : "Please enter a URL.");
      return;
    }
    if (!/^https?:\/\//i.test(urlValue)) {
      urlValue = `https://${urlValue}`;
    }

    const taskValue = rawTask || "Navigate and use the main features of this website";
    const settings = { task: taskValue, selectedTests, wcagVersion };
    lastSettingsRef.current = settings;
    analytics.auditStarted(urlValue, selectedTests, wcagVersion);
    runAudit(urlValue, settings);
  }

  // ── Form submit (kept as belt-and-suspenders for Enter key in inputs) ─────────
  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    e.stopPropagation();
    doSubmit();
  }

  // ── Retry (same URL + settings) ──────────────────────────────────────────────
  function handleRetry() {
    runAudit(submittedUrl, lastSettingsRef.current);
  }

  // ── Reset to form ────────────────────────────────────────────────────────────
  function handleReset() {
    if (phase === "running") analytics.auditCancelled(submittedUrl);
    wsRef.current?.close();
    if (coldStartTimerRef.current) clearTimeout(coldStartTimerRef.current);
    // Remove ?job= param so the form is clean
    const clean = window.location.pathname;
    window.history.replaceState(null, "", clean);
    setPhase("form");
    setEvents([]);
    setReport(null);
    setError("");
    setUrl("");
    setShowColdStart(false);
  }

  const inputStyle = {
    background: "var(--surface2)",
    border: "1px solid var(--border)",
    color: "var(--text)",
    outline: "none",
  };

  return (
    <div className="flex-1 max-w-4xl mx-auto w-full px-6 py-10">

      {/* ── Form ── */}
      {phase === "form" && (
        <form onSubmit={handleSubmit} className="space-y-8">
          <div>
            <h2 className="text-2xl font-bold tracking-tight" style={{ color: "var(--text)" }}>
              Run a PointCheck
            </h2>
            <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
              Enter a URL and choose which WCAG {wcagVersion} Level AA tests to run.
            </p>
          </div>

          <div className="space-y-2">
            <label htmlFor="url" className="block text-sm font-medium" style={{ color: "var(--text)" }}>
              Website URL <span style={{ color: "var(--crimson)" }} aria-hidden="true">*</span>
            </label>
            <input
              ref={urlInputRef}
              id="url"
              type="text"
              defaultValue={url}
              onChange={(e) => { setUrl(e.target.value); setError(""); }}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); doSubmit(); } }}
              placeholder="https://example.com"
              className="w-full rounded-lg px-4 py-2.5 text-sm transition-colors"
              style={{
                ...inputStyle,
                borderColor: error && !url.trim() ? "var(--crimson)" : "var(--border)",
                boxShadow: error && !url.trim() ? "0 0 0 2px rgba(255,51,102,0.25)" : "none",
              }}
              onFocus={(e) => (e.target.style.borderColor = "var(--lime)")}
              onBlur={(e) => (e.target.style.borderColor = error && !url.trim() ? "var(--crimson)" : "var(--border)")}
            />
            {error && !url.trim() && (
              <p className="text-xs font-medium mt-1" style={{ color: "var(--crimson)" }}>
                ↑ {error}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="block text-sm font-medium" style={{ color: "var(--text)" }}>
                WCAG Version
              </label>
              {wcagVersion === "2.2" && (
                <span className="text-xs" style={{ color: "var(--muted)" }}>Current standard</span>
              )}
            </div>
            <div className="flex rounded-lg overflow-hidden w-fit" style={{ border: "1px solid var(--border)" }}>
              {(["2.1", "2.2"] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => { setWcagVersion(v); analytics.wcagVersionSelected(v); }}
                  className="px-4 py-2 text-sm font-semibold transition-colors"
                  style={
                    wcagVersion === v
                      ? { background: "var(--lime)", color: "#0A0A0B" }
                      : { background: "var(--surface2)", color: "var(--muted)" }
                  }
                >
                  {v} AA
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <label htmlFor="task" className="block text-sm font-medium" style={{ color: "var(--text)" }}>
              Task Description
              <span className="ml-1 text-xs font-normal" style={{ color: "var(--muted)" }}>
                — what a real user would try to accomplish
              </span>
            </label>
            <input
              ref={taskInputRef}
              id="task"
              type="text"
              defaultValue={task}
              onChange={(e) => setTask(e.target.value)}
              className="w-full rounded-lg px-4 py-2.5 text-sm transition-colors"
              style={{ ...inputStyle }}
              onFocus={(e) => (e.target.style.borderColor = "var(--lime)")}
              onBlur={(e) => (e.target.style.borderColor = "var(--border)")}
            />
          </div>

          <TestSelector selected={selectedTests} onChange={setSelectedTests} wcagVersion={wcagVersion} />

          {/* Non-URL errors (e.g. no tests selected) shown near the button */}
          {error && url.trim() && (
            <div
              className="rounded-lg p-3 text-sm"
              style={{
                background: "rgba(255,51,102,0.1)",
                border: "1px solid rgba(255,51,102,0.3)",
                color: "var(--crimson)",
              }}
            >
              {error}
            </div>
          )}

          <button
            type="button"
            onClick={doSubmit}
            className="font-semibold px-6 py-2.5 rounded-lg text-sm transition-opacity hover:opacity-90 cursor-pointer"
            style={{ background: "var(--lime)", color: "#0A0A0B" }}
          >
            Run {selectedTests.length} Test{selectedTests.length !== 1 ? "s" : ""}
          </button>
        </form>
      )}

      {/* ── Landing sections (form phase only) ── */}
      {phase === "form" && (
        <div className="space-y-20 mt-24 pb-16">

          {/* Section A — Why PointCheck */}
          <section>
            <h2 className="text-xl font-bold mb-1" style={{ color: "var(--text)" }}>
              Why PointCheck beats a linter
            </h2>
            <p className="text-sm mb-8" style={{ color: "var(--muted)" }}>
              Most tools stop at the DOM. PointCheck drives a real browser and uses vision AI to catch what static analysis misses.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {[
                {
                  svg: <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6h-4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2z"/><path d="M4 8h4a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2z"/><path d="M12 4v16"/></svg>,
                  title: "Keyboard Navigation",
                  body: "Drives real Tab presses through interactive elements — catches traps and missing skip links that linters ignore.",
                },
                {
                  svg: <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m4.93 19.07 1.41-1.41"/><path d="m17.66 6.34 1.41-1.41"/></svg>,
                  title: "Focus Visibility",
                  body: "MolmoWeb-8B points to the focused element by pixel coordinate; Molmo-7B-D visually confirms the ring is present — not just a CSS property check.",
                },
                {
                  svg: <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 9h6"/><path d="M9 15h6"/><path d="M3 12h18"/></svg>,
                  title: "Page Structure",
                  body: "Alt text, headings, landmarks, ARIA, duplicate IDs, link text, and touch targets in one pass.",
                },
                {
                  svg: <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 2v20"/><path d="M2 12h20"/></svg>,
                  title: "Color & Contrast",
                  body: "Simulates Deuteranopia and walks every text node in the live DOM for real contrast ratios.",
                },
                {
                  svg: <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 3h6v18h-6"/><path d="M3 21V3"/><path d="M3 15h12"/><path d="M9 9h6"/></svg>,
                  title: "Resize & Reflow",
                  body: "200% zoom via Chrome DevTools Protocol — detects horizontal scroll and overflow-clipped text.",
                },
                {
                  svg: <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/></svg>,
                  title: "Form Error Handling",
                  body: "Submits invalid data and checks error messages are descriptive, associated, and suggest corrections.",
                },
              ].map((card) => (
                <div
                  key={card.title}
                  className="rounded-xl p-4 space-y-2"
                  style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
                >
                  <div className="w-7 h-7" style={{ color: "var(--lime)" }} aria-hidden="true">{card.svg}</div>
                  <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>{card.title}</p>
                  <p className="text-xs leading-relaxed" style={{ color: "var(--muted)" }}>{card.body}</p>
                </div>
              ))}
            </div>
          </section>

          {/* Section B — Live demo */}
          <section className="rounded-2xl p-8 text-center space-y-4" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
            <h2 className="text-xl font-bold" style={{ color: "var(--text)" }}>See it in action</h2>
            <p className="text-sm max-w-md mx-auto" style={{ color: "var(--muted)" }}>
              No account needed. Paste any URL above and run all six checks in about 90 seconds.
            </p>
            <button
              type="button"
              onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
              className="inline-block font-semibold px-6 py-2.5 rounded-lg text-sm transition-opacity hover:opacity-90 cursor-pointer"
              style={{ background: "var(--lime)", color: "#0A0A0B" }}
            >
              Try it now — free
            </button>
          </section>

          {/* Section C — How it works */}
          <section>
            <h2 className="text-xl font-bold mb-8" style={{ color: "var(--text)" }}>How it works</h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
              {[
                {
                  step: "1",
                  title: "Enter a URL",
                  body: "Paste any public URL and pick which WCAG 2.1 or 2.2 Level AA tests to run.",
                },
                {
                  step: "2",
                  title: "Real browser + AI",
                  body: "A headless Chrome instance drives the page while MolmoWeb-8B, Molmo-7B-D, and OLMo-3 analyse visuals and write the report.",
                },
                {
                  step: "3",
                  title: "Actionable report",
                  body: "Get a compliance score, per-criterion findings, and a downloadable PDF — ready to share with your team.",
                },
              ].map((item) => (
                <div key={item.step} className="flex gap-4 items-start">
                  <div
                    className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold"
                    style={{ background: "var(--lime)", color: "#0A0A0B" }}
                    aria-hidden="true"
                  >
                    {item.step}
                  </div>
                  <div>
                    <p className="text-sm font-semibold mb-1" style={{ color: "var(--text)" }}>{item.title}</p>
                    <p className="text-xs leading-relaxed" style={{ color: "var(--muted)" }}>{item.body}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

        </div>
      )}

      {/* ── Loading permalink ── */}
      {phase === "loading" && (
        <div className="flex flex-col items-center justify-center gap-4 py-24">
          <div
            className="w-8 h-8 rounded-full border-2 border-t-transparent animate-spin"
            style={{ borderColor: "var(--lime)", borderTopColor: "transparent" }}
            aria-label="Loading report"
          />
          <p className="text-sm" style={{ color: "var(--muted)" }}>Loading report…</p>
        </div>
      )}

      {/* ── Running ── */}
      {phase === "running" && (
        <ProgressDisplay
          events={events}
          showColdStart={showColdStart}
          onCancel={handleReset}
        />
      )}

      {/* ── Done ── */}
      {phase === "done" && (
        <div className="space-y-6">
          {error && !report && (
            /* Fatal error — no results to show */
            <div
              className="rounded-xl p-6 space-y-4"
              style={{
                background: "rgba(255,51,102,0.07)",
                border: "1px solid rgba(255,51,102,0.25)",
              }}
            >
              <div>
                <p className="text-sm font-semibold mb-1" style={{ color: "var(--crimson)" }}>
                  Something went wrong
                </p>
                <p className="text-sm" style={{ color: "var(--muted)" }}>
                  {error}
                </p>
              </div>
              <div className="flex gap-3 flex-wrap">
                <button
                  onClick={handleRetry}
                  className="text-sm font-semibold px-4 py-2 rounded-lg transition-opacity hover:opacity-90 cursor-pointer"
                  style={{ background: "var(--lime)", color: "#0A0A0B" }}
                >
                  Try again
                </button>
                <button
                  onClick={handleReset}
                  className="text-sm px-4 py-2 rounded-lg transition-colors cursor-pointer"
                  style={{
                    background: "var(--surface2)",
                    border: "1px solid var(--border)",
                    color: "var(--muted)",
                  }}
                >
                  Change settings
                </button>
              </div>
            </div>
          )}

          {error && report && (
            /* Non-fatal error alongside a partial report */
            <div
              className="rounded-lg p-3 text-sm"
              style={{
                background: "rgba(255,51,102,0.1)",
                border: "1px solid rgba(255,51,102,0.3)",
                color: "var(--crimson)",
              }}
            >
              <strong>Note:</strong> {error}
            </div>
          )}

          {blockWarning && (
            <div
              className="rounded-xl p-4 text-sm space-y-2"
              style={{
                background: "rgba(255,51,102,0.07)",
                border: "1px solid rgba(255,51,102,0.3)",
              }}
            >
              <p className="font-semibold" style={{ color: "var(--crimson)" }}>
                ⛔ This site likely blocked automated access
              </p>
              <p style={{ color: "var(--muted)" }}>
                The scanner was probably stopped by bot protection or a CAPTCHA challenge before
                it could collect valid test data. Any results shown below are not meaningful.
              </p>
              <p style={{ color: "var(--muted)" }}>
                <span className="font-medium" style={{ color: "var(--text)" }}>Accessibility note:</span>{" "}
                Sites that rely on visual-only CAPTCHAs may themselves fail{" "}
                <span className="font-mono text-xs" style={{ color: "var(--lime)" }}>WCAG 2.1 SC 1.1.1</span>{" "}
                (Non-text Content) — challenge images without an accessible text alternative or
                audio equivalent exclude users who rely on assistive technology.
              </p>
            </div>
          )}

          {report && <ResultsDashboard report={report} url={submittedUrl} blocked={!!blockWarning} />}

          <button
            onClick={handleReset}
            className="text-sm underline transition-opacity hover:opacity-70"
            style={{ color: "var(--lime)" }}
          >
            Run another PointCheck
          </button>
        </div>
      )}
    </div>
  );
}
