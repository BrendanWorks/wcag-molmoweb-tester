"use client";

import { useEffect, useRef } from "react";
import { TEST_OPTIONS } from "./TestSelector";

interface Event {
  type: string;
  test?: string;
  test_name?: string;
  message?: string;
  index?: number;
  total?: number;
  data?: Record<string, unknown>;
}

interface Props {
  events: object[];
  showColdStart: boolean;
  onCancel: () => void;
}

const TEST_NAME: Record<string, string> = Object.fromEntries(
  TEST_OPTIONS.map((t) => [t.id, t.label])
);

function StatusDot({ result }: { result?: string }) {
  if (!result)
    return (
      <span
        className="inline-block w-2 h-2 rounded-full"
        style={{ background: "var(--border)" }}
      />
    );
  const colors: Record<string, string> = {
    pass: "var(--lime)",
    fail: "var(--crimson)",
    warning: "var(--amber)",
    error: "var(--crimson)",
  };
  return (
    <span
      className="inline-block w-2 h-2 rounded-full"
      style={{ background: colors[result] ?? "var(--muted)" }}
    />
  );
}

export default function ProgressDisplay({ events, showColdStart, onCancel }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const typed = events as Event[];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  const testResults: Record<string, string> = {};
  let currentTest = "";
  let totalTests = 0;
  let completedTests = 0;

  for (const ev of typed) {
    if (ev.type === "test_start") {
      currentTest = ev.test ?? "";
      totalTests = ev.total ?? totalTests;
    }
    if (ev.type === "test_complete") completedTests++;
    if (ev.type === "result" && ev.test) {
      testResults[ev.test] = (ev.data?.result as string) ?? "unknown";
    }
  }

  const progress = totalTests > 0 ? (completedTests / totalTests) * 100 : 0;

  return (
    <div className="space-y-6">
      {/* ── Header row ── */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <h2
            className="text-xl font-bold tracking-tight"
            style={{ color: "var(--text)" }}
          >
            Running Tests…
          </h2>
          <button
            onClick={onCancel}
            className="text-sm transition-colors rounded px-2 py-1"
            style={{ color: "var(--muted)" }}
            onMouseEnter={(e) =>
              ((e.target as HTMLElement).style.color = "var(--crimson)")
            }
            onMouseLeave={(e) =>
              ((e.target as HTMLElement).style.color = "var(--muted)")
            }
          >
            Cancel
          </button>
        </div>

        {totalTests > 0 && (
          <div className="mt-2">
            <div
              className="flex justify-between text-xs mb-1"
              style={{ color: "var(--muted)" }}
            >
              <span>
                {completedTests} / {totalTests} tests complete
              </span>
              <span style={{ color: "var(--lime)" }}>{Math.round(progress)}%</span>
            </div>
            <div
              className="w-full h-1.5 rounded-full overflow-hidden"
              style={{ background: "var(--surface2)" }}
            >
              <div
                className="h-1.5 rounded-full transition-all duration-500"
                style={{ width: `${progress}%`, background: "var(--lime)" }}
              />
            </div>
          </div>
        )}
      </div>

      {/* ── Cold-start notice ── */}
      {showColdStart && (
        <div
          className="flex items-start gap-3 rounded-lg px-4 py-3 text-sm"
          style={{
            background: "rgba(255,184,0,0.08)",
            border: "1px solid rgba(255,184,0,0.25)",
            color: "var(--amber)",
          }}
        >
          <span className="mt-0.5 shrink-0">⏳</span>
          <span>
            The backend is loading its models — this takes up to 30 seconds on the
            first run. Hang tight.
          </span>
        </div>
      )}

      {/* ── Per-test status pills ── */}
      {Object.keys(testResults).length > 0 && (
        <div className="flex flex-wrap gap-2">
          {Object.entries(testResults).map(([id, result]) => (
            <span
              key={id}
              className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full"
              style={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                color: "var(--text)",
              }}
            >
              <StatusDot result={result} />
              {TEST_NAME[id] ?? id}
            </span>
          ))}
          {currentTest && !testResults[currentTest] && (
            <span
              className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full animate-pulse"
              style={{
                background: "rgba(204,255,0,0.08)",
                border: "1px solid rgba(204,255,0,0.25)",
                color: "var(--lime)",
              }}
            >
              <span
                className="inline-block w-2 h-2 rounded-full"
                style={{ background: "var(--lime)" }}
              />
              {TEST_NAME[currentTest] ?? currentTest}
            </span>
          )}
        </div>
      )}

      {/* ── Event log ── */}
      <div
        className="rounded-xl p-4 h-80 overflow-y-auto font-mono text-xs space-y-1"
        style={{ background: "#0D0D0E", border: "1px solid var(--border)" }}
      >
        {typed.map((ev, i) => {
          if (ev.type === "progress") {
            return (
              <p key={i} style={{ color: "var(--muted)" }}>
                <span style={{ color: "var(--border)" }}>  › </span>
                {ev.message}
              </p>
            );
          }
          if (ev.type === "status") {
            return (
              <p key={i} style={{ color: "var(--lime)" }}>
                <span style={{ color: "rgba(204,255,0,0.4)" }}>  ● </span>
                {ev.message}
              </p>
            );
          }
          if (ev.type === "test_start") {
            return (
              <p key={i} className="mt-2" style={{ color: "var(--text)" }}>
                ▶ {ev.test_name}
              </p>
            );
          }
          if (ev.type === "test_complete") {
            return (
              <p key={i} style={{ color: "var(--lime)" }}>
                ✓ Complete: {TEST_NAME[ev.test ?? ""] ?? ev.test}
              </p>
            );
          }
          if (ev.type === "result") {
            const r = ev.data?.result as string;
            const color =
              r === "pass"
                ? "var(--lime)"
                : r === "fail"
                ? "var(--crimson)"
                : "var(--amber)";
            return (
              <p key={i} style={{ color }}>
                {r === "pass" ? "✓" : "✗"} {r?.toUpperCase()}
                {ev.data?.failure_reason
                  ? ` — ${String(ev.data.failure_reason).slice(0, 120)}`
                  : ""}
              </p>
            );
          }
          if (ev.type === "error") {
            return (
              <p key={i} style={{ color: "var(--crimson)" }}>
                ✗ Error: {ev.message}
              </p>
            );
          }
          if (ev.type === "page_error") {
            return (
              <p key={i} style={{ color: "var(--crimson)", fontWeight: "bold" }}>
                ⛔ {(ev as unknown as Record<string, unknown>).error as string}
              </p>
            );
          }
          return null;
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
