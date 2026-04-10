"use client";

import { useState, useRef, useEffect } from "react";
import TestSelector, { TEST_OPTIONS } from "@/components/TestSelector";
import ProgressDisplay from "@/components/ProgressDisplay";
import ResultsDashboard from "@/components/ResultsDashboard";

type Phase = "form" | "running" | "done";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");

export default function AuditForm() {
  const [url, setUrl] = useState("");
  const [task, setTask] = useState("Navigate and use the main features of this website");
  const [selectedTests, setSelectedTests] = useState<string[]>(
    TEST_OPTIONS.map((t) => t.id)
  );
  const [useQuantization, setUseQuantization] = useState(false);
  const [wcagVersion, setWcagVersion] = useState<"2.1" | "2.2">("2.2");
  const [phase, setPhase] = useState<Phase>("form");
  const [events, setEvents] = useState<object[]>([]);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [submittedUrl, setSubmittedUrl] = useState("");
  const [showColdStart, setShowColdStart] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const coldStartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Keep a snapshot of settings for retry
  const lastSettingsRef = useRef({ task, selectedTests, useQuantization, wcagVersion });
  // Collect screenshot_b64 from streaming result events (stripped from done report to save WS payload)
  const screenshotMapRef = useRef<Record<string, string>>({});

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
    useQuantization: boolean;
    wcagVersion: "2.1" | "2.2";
  }) {
    wsRef.current?.close();
    if (coldStartTimerRef.current) clearTimeout(coldStartTimerRef.current);

    setSubmittedUrl(urlValue);
    setError("");
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
          use_quantization: settings.useQuantization,
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
          setReport(report);
          setPhase("done");
          ws.close();
        }
        if (msg.type === "error") {
          setError(msg.message as string);
          setPhase("done");
          ws.close();
        }
      };

      ws.onerror = () => {
        dismissColdStart();
        setError("WebSocket connection failed. Is the backend running on port 8000?");
        setPhase("done");
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
      setError(err instanceof Error ? err.message : String(err));
      setPhase("done");
    }
  }

  // ── Form submit ──────────────────────────────────────────────────────────────
  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    e.stopPropagation();

    let urlValue = url.trim();
    if (!urlValue || selectedTests.length === 0) {
      setError(urlValue ? "Please select at least one test." : "Please enter a URL.");
      return;
    }
    // Auto-prepend https:// if the user omitted the protocol
    if (!/^https?:\/\//i.test(urlValue)) {
      urlValue = `https://${urlValue}`;
    }

    const settings = { task, selectedTests, useQuantization, wcagVersion };
    lastSettingsRef.current = settings;
    runAudit(urlValue, settings);
  }

  // ── Retry (same URL + settings) ──────────────────────────────────────────────
  function handleRetry() {
    runAudit(submittedUrl, lastSettingsRef.current);
  }

  // ── Reset to form ────────────────────────────────────────────────────────────
  function handleReset() {
    wsRef.current?.close();
    if (coldStartTimerRef.current) clearTimeout(coldStartTimerRef.current);
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
              Enter a URL and choose which WCAG {wcagVersion} Level AA tests to run. Powered by
              Allen AI&apos;s OLMo3 and Molmo2 models.
            </p>
          </div>

          {error && (
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

          <div className="space-y-2">
            <label htmlFor="url" className="block text-sm font-medium" style={{ color: "var(--text)" }}>
              Website URL <span style={{ color: "var(--crimson)" }} aria-hidden="true">*</span>
            </label>
            <input
              id="url"
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com"
              className="w-full rounded-lg px-4 py-2.5 text-sm transition-colors"
              style={{ ...inputStyle, borderColor: "var(--border)" }}
              onFocus={(e) => (e.target.style.borderColor = "var(--lime)")}
              onBlur={(e) => (e.target.style.borderColor = "var(--border)")}
            />
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
                  onClick={() => setWcagVersion(v)}
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
              id="task"
              type="text"
              value={task}
              onChange={(e) => setTask(e.target.value)}
              className="w-full rounded-lg px-4 py-2.5 text-sm transition-colors"
              style={{ ...inputStyle }}
              onFocus={(e) => (e.target.style.borderColor = "var(--lime)")}
              onBlur={(e) => (e.target.style.borderColor = "var(--border)")}
            />
          </div>

          <TestSelector selected={selectedTests} onChange={setSelectedTests} wcagVersion={wcagVersion} />

          <div className="flex items-center gap-2">
            <input
              id="quantize"
              type="checkbox"
              checked={useQuantization}
              onChange={(e) => setUseQuantization(e.target.checked)}
              className="h-4 w-4 rounded"
              style={{ accentColor: "var(--lime)" }}
            />
            <label htmlFor="quantize" className="text-sm" style={{ color: "var(--muted)" }}>
              Use 4-bit quantization{" "}
              <span style={{ color: "var(--border)" }}>(less VRAM, slower inference)</span>
            </label>
          </div>

          <button
            type="submit"
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
                  icon: "⌨",
                  title: "Keyboard Navigation",
                  body: "Drives real Tab presses through interactive elements — catches traps and missing skip links that linters ignore.",
                },
                {
                  icon: "👁",
                  title: "Focus Visibility",
                  body: "Molmo2 visually confirms each focus ring exists — not just a CSS property check that CSS resets can fool.",
                },
                {
                  icon: "🏗",
                  title: "Page Structure",
                  body: "Alt text, headings, landmarks, ARIA, duplicate IDs, link text, and touch targets in one pass.",
                },
                {
                  icon: "🎨",
                  title: "Color & Contrast",
                  body: "Simulates Deuteranopia and walks every text node in the live DOM for real contrast ratios.",
                },
                {
                  icon: "🔍",
                  title: "Resize & Reflow",
                  body: "200% zoom via Chrome DevTools Protocol — detects horizontal scroll and overflow-clipped text.",
                },
                {
                  icon: "📋",
                  title: "Form Error Handling",
                  body: "Submits invalid data and checks error messages are descriptive, associated, and suggest corrections.",
                },
              ].map((card) => (
                <div
                  key={card.title}
                  className="rounded-xl p-4 space-y-2"
                  style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
                >
                  <div className="text-2xl" aria-hidden="true">{card.icon}</div>
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
                  body: "A headless Chrome instance drives the page while OLMo3 and Molmo2 analyse structure and visuals.",
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

          {report && <ResultsDashboard report={report} url={submittedUrl} />}

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
