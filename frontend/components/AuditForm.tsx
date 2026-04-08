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
  const [phase, setPhase] = useState<Phase>("form");
  const [events, setEvents] = useState<object[]>([]);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [submittedUrl, setSubmittedUrl] = useState("");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    return () => { wsRef.current?.close(); };
  }, []);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    e.stopPropagation();

    const urlValue = url.trim();
    if (!urlValue || selectedTests.length === 0) {
      setError(urlValue ? "Please select at least one test." : "Please enter a URL.");
      return;
    }

    setSubmittedUrl(urlValue);
    setError("");
    setEvents([]);
    setReport(null);
    setPhase("running");

    try {
      const res = await fetch(`${API_BASE}/api/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: urlValue,
          tests: selectedTests,
          task: task.trim() || "Navigate and use the main features of this website",
          use_quantization: useQuantization,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? `Server error ${res.status}`);
      }
      const { run_id } = await res.json() as { run_id: string };

      const ws = new WebSocket(`${WS_BASE}/ws/${run_id}`);
      wsRef.current = ws;

      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data as string) as Record<string, unknown>;
        setEvents((prev) => [...prev, msg]);
        if (msg.type === "done") {
          setReport(msg.report as Record<string, unknown>);
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
        setError("WebSocket connection failed. Is the backend running on port 8000?");
        setPhase("done");
      };

      ws.onclose = (ev) => {
        if (!ev.wasClean && phase === "running") {
          setError("Connection to backend dropped unexpectedly.");
          setPhase("done");
        }
      };
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase("done");
    }
  }

  function handleReset() {
    wsRef.current?.close();
    setPhase("form");
    setEvents([]);
    setReport(null);
    setError("");
    setUrl("");
  }

  const inputStyle = {
    background: "var(--surface2)",
    border: "1px solid var(--border)",
    color: "var(--text)",
    outline: "none",
  };

  return (
    <div className="flex-1 max-w-4xl mx-auto w-full px-6 py-10">
      {phase === "form" && (
        <form onSubmit={handleSubmit} className="space-y-8">
          <div>
            <h2 className="text-2xl font-bold tracking-tight" style={{ color: "var(--text)" }}>
              Run a PointCheck
            </h2>
            <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
              Enter a URL and choose which WCAG 2.1 Level AA tests to run. Powered by
              Allen AI&apos;s OLMo2 and Molmo2 models.
            </p>
          </div>

          {error && (
            <div
              className="rounded-lg p-3 text-sm"
              style={{ background: "rgba(255,51,102,0.1)", border: "1px solid rgba(255,51,102,0.3)", color: "var(--crimson)" }}
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
              style={{
                ...inputStyle,
                borderColor: "var(--border)",
              }}
              onFocus={(e) => (e.target.style.borderColor = "var(--lime)")}
              onBlur={(e) => (e.target.style.borderColor = "var(--border)")}
            />
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

          <TestSelector selected={selectedTests} onChange={setSelectedTests} />

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

      {phase === "running" && (
        <ProgressDisplay events={events} onCancel={handleReset} />
      )}

      {phase === "done" && (
        <div className="space-y-6">
          {error && (
            <div
              className="rounded-lg p-4 text-sm"
              style={{ background: "rgba(255,51,102,0.1)", border: "1px solid rgba(255,51,102,0.3)", color: "var(--crimson)" }}
            >
              <strong>Error:</strong> {error}
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
