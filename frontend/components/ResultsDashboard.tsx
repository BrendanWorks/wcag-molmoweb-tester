"use client";

import { useState } from "react";

interface Molmo2Point {
  x: number;
  y: number;
}

interface FocusStep {
  tab: number;
  focus_info?: {
    tag: string;
    text: string;
    x: number;
    y: number;
    width: number;
    height: number;
  };
  analysis: {
    result: string;
    layer: string;
    focused_element: string;
    css_indicator?: string;
    molmo2_point?: Molmo2Point;
    failure_reason?: string;
  };
}

interface StructureIssue {
  criterion: string;
  severity: string;
  description: string;
  examples?: string[];
  fix?: string;
}

interface TestDetails {
  molmo2_used?: boolean;
  molmo2_warnings?: number;
  steps?: FocusStep[];
  tabs_tested?: number;
  failure_count?: number;
  issues?: StructureIssue[];
  critical_count?: number;
  major_count?: number;
  minor_count?: number;
  [key: string]: unknown;
}

interface TestSummary {
  test_id: string;
  test_name: string;
  result: string;
  severity: string;
  failure_reason: string;
  wcag_criteria: string[];
  recommendation: string;
  screenshot_path?: string;
  screenshot_b64?: string;
  details?: TestDetails;
}

interface CriteriaFailure {
  criterion: string;
  label: string;
  failure_count: number;
}

interface Report {
  run_id: string;
  url: string;
  generated_at: string;
  overall_status: string;
  compliance_percentage: number;
  narrative?: string;
  summary: {
    total_tests: number;
    passed: number;
    failed: number;
    warnings: number;
    errors: number;
  };
  top_criteria_failures: CriteriaFailure[];
  test_summaries: TestSummary[];
}

// ── Severity styling ──────────────────────────────────────────────────────────
const SEVERITY_STYLE: Record<string, { bg: string; color: string; border: string }> = {
  critical: { bg: "rgba(255,51,102,0.1)",  color: "var(--crimson)", border: "rgba(255,51,102,0.3)" },
  major:    { bg: "rgba(255,120,0,0.1)",   color: "#FF7800",        border: "rgba(255,120,0,0.3)" },
  minor:    { bg: "rgba(255,184,0,0.1)",   color: "var(--amber)",   border: "rgba(255,184,0,0.3)" },
};

const RESULT_STYLE: Record<string, { bg: string; color: string; border: string }> = {
  pass:    { bg: "rgba(204,255,0,0.08)",  color: "var(--lime)",    border: "rgba(204,255,0,0.25)" },
  fail:    { bg: "rgba(255,51,102,0.08)", color: "var(--crimson)", border: "rgba(255,51,102,0.25)" },
  warning: { bg: "rgba(255,184,0,0.08)", color: "var(--amber)",   border: "rgba(255,184,0,0.25)" },
  error:   { bg: "rgba(255,120,0,0.08)", color: "#FF7800",        border: "rgba(255,120,0,0.25)" },
};

const RESULT_ICON: Record<string, string> = {
  pass: "✓", fail: "✗", warning: "⚠", error: "!",
};

const STATUS_STYLE: Record<string, { label: string; color: string; bg: string }> = {
  compliant:       { label: "Compliant",      color: "var(--lime)",    bg: "rgba(204,255,0,0.1)" },
  issues_found:    { label: "Issues Found",   color: "var(--amber)",   bg: "rgba(255,184,0,0.1)" },
  critical_issues: { label: "Critical Issues",color: "var(--crimson)", bg: "rgba(255,51,102,0.1)" },
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const card = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: "12px",
};

export default function ResultsDashboard({
  report,
  url,
}: {
  report: Record<string, unknown>;
  url: string;
}) {
  const r = report as unknown as Report;
  const [expandedTest, setExpandedTest] = useState<string | null>(null);
  const status = STATUS_STYLE[r.overall_status] ?? STATUS_STYLE.issues_found;

  function downloadJson() {
    const blob = new Blob([JSON.stringify(r, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `pointcheck-${r.run_id?.slice(0, 8)}.json`;
    a.click();
  }

  function downloadCsv() {
    const rows = [
      ["Test", "Result", "Severity", "WCAG Criteria", "Failure Reason", "Recommendation"],
      ...(r.test_summaries ?? []).map((ts: TestSummary) => [
        ts.test_name, ts.result, ts.severity,
        ts.wcag_criteria.join("|"), ts.failure_reason, ts.recommendation,
      ]),
    ];
    const csv = rows.map((row) => row.map((v: unknown) => `"${String(v).replace(/"/g, "'")}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `pointcheck-${r.run_id?.slice(0, 8)}.csv`;
    a.click();
  }

  const complianceColor =
    r.compliance_percentage >= 80 ? "var(--lime)" :
    r.compliance_percentage >= 50 ? "var(--amber)" : "var(--crimson)";

  return (
    <div className="space-y-4">

      {/* ── Header card ── */}
      <div style={card} className="p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <span
              className="text-xs font-semibold px-2.5 py-1 rounded-full inline-block mb-2"
              style={{ color: status.color, background: status.bg }}
            >
              {status.label}
            </span>
            <h2 className="text-lg font-bold break-all" style={{ color: "var(--text)" }}>{url}</h2>
            <p className="text-xs mt-1 font-mono" style={{ color: "var(--muted)" }}>
              {r.run_id} · {new Date(r.generated_at).toLocaleString()}
            </p>
          </div>
          <div className="text-center">
            <p className="text-5xl font-bold tabular-nums" style={{ color: complianceColor }}>
              {r.compliance_percentage}%
            </p>
            <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>Compliance</p>
          </div>
        </div>

        {/* Summary counts */}
        <div className="grid grid-cols-4 gap-3 mt-5">
          {[
            { label: "Passed",   value: r.summary.passed,      style: RESULT_STYLE.pass },
            { label: "Failed",   value: r.summary.failed,      style: RESULT_STYLE.fail },
            { label: "Warnings", value: r.summary.warnings,    style: RESULT_STYLE.warning },
            { label: "Total",    value: r.summary.total_tests, style: { bg: "var(--surface2)", color: "var(--text)", border: "var(--border)" } },
          ].map((s) => (
            <div
              key={s.label}
              className="rounded-lg p-3 text-center"
              style={{ background: s.style.bg, border: `1px solid ${s.style.border}` }}
            >
              <p className="text-2xl font-bold tabular-nums" style={{ color: s.style.color }}>{s.value}</p>
              <p className="text-xs font-medium mt-0.5" style={{ color: "var(--muted)" }}>{s.label}</p>
            </div>
          ))}
        </div>

        {/* Downloads */}
        <div className="flex gap-3 mt-5">
          {[
            { label: "Download JSON", fn: downloadJson },
            { label: "Download CSV",  fn: downloadCsv },
          ].map((btn) => (
            <button
              key={btn.label}
              onClick={btn.fn}
              className="text-xs rounded-lg px-3 py-1.5 transition-opacity hover:opacity-80"
              style={{ background: "var(--surface2)", border: "1px solid var(--border)", color: "var(--muted)" }}
            >
              {btn.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── OLMo3 narrative ── */}
      {r.narrative && (
        <div style={card} className="p-5">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--muted)" }}>
              AI Assessment
            </span>
            <span
              className="text-xs rounded-full px-2 py-0.5 font-medium"
              style={{ background: "rgba(204,255,0,0.1)", color: "var(--lime)", border: "1px solid rgba(204,255,0,0.2)" }}
            >
              OLMo3-7B
            </span>
          </div>
          <div className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text)" }}>
            {r.narrative}
          </div>
        </div>
      )}

      {/* ── Top failing criteria ── */}
      {r.top_criteria_failures?.length > 0 && (
        <div style={card} className="p-5">
          <h3 className="text-xs font-semibold uppercase tracking-widest mb-4" style={{ color: "var(--muted)" }}>
            Top Failing WCAG Criteria
          </h3>
          <div className="space-y-3">
            {r.top_criteria_failures.map((cf) => (
              <div key={cf.criterion} className="flex items-center gap-3">
                <span className="font-mono text-xs w-12" style={{ color: "var(--muted)" }}>{cf.criterion}</span>
                <span className="text-sm flex-1" style={{ color: "var(--text)" }}>{cf.label}</span>
                <span className="text-xs font-bold tabular-nums" style={{ color: "var(--crimson)" }}>
                  {cf.failure_count}×
                </span>
                <div className="w-24 h-1 rounded-full overflow-hidden" style={{ background: "var(--surface2)" }}>
                  <div
                    className="h-1 rounded-full"
                    style={{
                      width: `${Math.min(100, (cf.failure_count / (r.summary.total_tests || 1)) * 100)}%`,
                      background: "var(--crimson)",
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Per-test results ── */}
      <div className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-widest px-1" style={{ color: "var(--muted)" }}>
          Test Results
        </h3>
        {r.test_summaries?.map((ts) => {
          const rs = RESULT_STYLE[ts.result] ?? RESULT_STYLE.warning;
          const expanded = expandedTest === ts.test_id;
          return (
            <div
              key={ts.test_id}
              style={{ ...card, overflow: "hidden" }}
            >
              <button
                onClick={() => setExpandedTest(expanded ? null : ts.test_id)}
                className="w-full flex items-center gap-3 p-4 text-left transition-colors"
                style={{ background: expanded ? "var(--surface2)" : "transparent" }}
                aria-expanded={expanded}
              >
                <span
                  className="flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
                  style={{ background: rs.bg, border: `1px solid ${rs.border}`, color: rs.color }}
                >
                  {RESULT_ICON[ts.result] ?? "?"}
                </span>
                <span className="flex-1 font-medium text-sm" style={{ color: "var(--text)" }}>
                  {ts.test_name}
                </span>
                {ts.severity && ts.result === "fail" && (
                  <span
                    className="text-xs px-2 py-0.5 rounded font-medium"
                    style={{
                      background: SEVERITY_STYLE[ts.severity]?.bg ?? "transparent",
                      color: SEVERITY_STYLE[ts.severity]?.color ?? "var(--muted)",
                      border: `1px solid ${SEVERITY_STYLE[ts.severity]?.border ?? "var(--border)"}`,
                    }}
                  >
                    {ts.severity}
                  </span>
                )}
                {ts.wcag_criteria?.map((c) => (
                  <span
                    key={c}
                    className="hidden sm:inline text-xs font-mono px-1.5 py-0.5 rounded"
                    style={{ background: "var(--surface2)", color: "var(--muted)", border: "1px solid var(--border)" }}
                  >
                    {c}
                  </span>
                ))}
                <span className="text-xs ml-1" style={{ color: "var(--muted)" }}>
                  {expanded ? "▲" : "▼"}
                </span>
              </button>

              {expanded && (
                <div
                  className="p-4 space-y-4 text-sm"
                  style={{ borderTop: "1px solid var(--border)" }}
                >
                  {ts.failure_reason && (
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-widest mb-1.5" style={{ color: "var(--muted)" }}>
                        Failure
                      </p>
                      <p style={{ color: "var(--text)" }}>{ts.failure_reason}</p>
                    </div>
                  )}
                  {ts.recommendation && (
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-widest mb-1.5" style={{ color: "var(--muted)" }}>
                        Recommendation
                      </p>
                      <p style={{ color: "var(--text)" }}>{ts.recommendation}</p>
                    </div>
                  )}
                  {ts.wcag_criteria?.length > 0 && (
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-widest mb-1.5" style={{ color: "var(--muted)" }}>
                        WCAG Criteria
                      </p>
                      <div className="flex flex-wrap gap-1">
                        {ts.wcag_criteria.map((c) => (
                          <span
                            key={c}
                            className="font-mono text-xs px-2 py-0.5 rounded"
                            style={{ background: "var(--surface2)", color: "var(--lime)", border: "1px solid var(--border)" }}
                          >
                            {c}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Molmo2 visual confirmation (focus_indicator) */}
                  {ts.test_id === "focus_indicator" && ts.details && (
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-widest mb-2" style={{ color: "var(--muted)" }}>
                        Visual Confirmation
                      </p>
                      <div className="flex items-center gap-2 flex-wrap mb-2">
                        <span
                          className="text-xs px-2 py-0.5 rounded-full font-medium"
                          style={ts.details.molmo2_used
                            ? { background: "rgba(204,255,0,0.1)", color: "var(--lime)", border: "1px solid rgba(204,255,0,0.2)" }
                            : { background: "var(--surface2)", color: "var(--muted)", border: "1px solid var(--border)" }
                          }
                        >
                          {ts.details.molmo2_used ? "Molmo2-4B" : "CSS only"}
                        </span>
                        {ts.details.tabs_tested !== undefined && (
                          <span className="text-xs" style={{ color: "var(--muted)" }}>
                            {ts.details.tabs_tested} element{ts.details.tabs_tested !== 1 ? "s" : ""} checked
                          </span>
                        )}
                        {!!ts.details.failure_count && ts.details.failure_count > 0 && (
                          <span className="text-xs font-medium" style={{ color: "var(--crimson)" }}>
                            {ts.details.failure_count} missing focus indicator{ts.details.failure_count !== 1 ? "s" : ""}
                          </span>
                        )}
                        {!!ts.details.molmo2_warnings && ts.details.molmo2_warnings > 0 && (
                          <span className="text-xs font-medium" style={{ color: "var(--amber)" }}>
                            {ts.details.molmo2_warnings} visual warning{ts.details.molmo2_warnings !== 1 ? "s" : ""}
                          </span>
                        )}
                      </div>
                      {ts.details.steps && ts.details.steps
                        .filter((s) => s.analysis.layer === "molmo2_visual")
                        .slice(0, 15)
                        .map((step) => {
                          const found = !!step.analysis.molmo2_point;
                          const fi = step.focus_info;
                          return (
                            <div
                              key={step.tab}
                              className="text-xs rounded-lg p-2 mb-1"
                              style={{
                                background: found ? "rgba(204,255,0,0.05)" : "rgba(255,51,102,0.05)",
                                border: `1px solid ${found ? "rgba(204,255,0,0.15)" : "rgba(255,51,102,0.15)"}`,
                              }}
                            >
                              <div className="flex items-center gap-1 flex-wrap">
                                <span className="font-semibold" style={{ color: found ? "var(--lime)" : "var(--crimson)" }}>
                                  Tab {step.tab}
                                </span>
                                <span style={{ color: "var(--border)" }}>·</span>
                                <span className="truncate max-w-[200px]" style={{ color: "var(--text)" }}>
                                  {step.analysis.focused_element}
                                </span>
                                <span style={{ color: "var(--border)" }}>·</span>
                                {found ? (
                                  <span className="font-mono" style={{ color: "var(--lime)" }}>
                                    ({step.analysis.molmo2_point!.x}, {step.analysis.molmo2_point!.y})px ✓
                                  </span>
                                ) : (
                                  <span className="font-mono font-semibold" style={{ color: "var(--crimson)" }}>
                                    not found ✗
                                  </span>
                                )}
                              </div>
                              {!found && fi && (
                                <div className="mt-1 flex items-center gap-2" style={{ color: "var(--muted)" }}>
                                  <span style={{ color: "var(--crimson)" }}>↳</span>
                                  <span>
                                    Expected at{" "}
                                    <span className="font-mono" style={{ color: "var(--text)" }}>
                                      ({Math.round(fi.x)}, {Math.round(fi.y)})
                                    </span>
                                    {" "}—{" "}
                                    <span className="font-mono" style={{ color: "var(--text)" }}>
                                      {Math.round(fi.width)}×{Math.round(fi.height)}px
                                    </span>
                                  </span>
                                  {step.analysis.css_indicator && (
                                    <span className="truncate" style={{ color: "var(--muted)" }}>
                                      · {step.analysis.css_indicator}
                                    </span>
                                  )}
                                </div>
                              )}
                              {found && step.analysis.css_indicator && (
                                <div className="mt-0.5 truncate" style={{ color: "var(--muted)" }}>
                                  {step.analysis.css_indicator}
                                </div>
                              )}
                            </div>
                          );
                        })}
                    </div>
                  )}

                  {/* Page Structure issue breakdown */}
                  {ts.test_id === "page_structure" && ts.details?.issues && ts.details.issues.length > 0 && (
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-widest mb-2" style={{ color: "var(--muted)" }}>
                        Issues Found
                      </p>
                      <div className="flex items-center gap-3 flex-wrap mb-3 text-xs">
                        {!!ts.details.critical_count && ts.details.critical_count > 0 && (
                          <span className="font-medium" style={{ color: "var(--crimson)" }}>{ts.details.critical_count} critical</span>
                        )}
                        {!!ts.details.major_count && ts.details.major_count > 0 && (
                          <span className="font-medium" style={{ color: "#FF7800" }}>{ts.details.major_count} major</span>
                        )}
                        {!!ts.details.minor_count && ts.details.minor_count > 0 && (
                          <span className="font-medium" style={{ color: "var(--amber)" }}>{ts.details.minor_count} minor</span>
                        )}
                      </div>
                      <div className="space-y-2">
                        {ts.details.issues.map((issue, idx) => {
                          const sev = SEVERITY_STYLE[issue.severity] ?? SEVERITY_STYLE.minor;
                          return (
                            <div
                              key={idx}
                              className="rounded-lg p-3 text-xs"
                              style={{ background: sev.bg, border: `1px solid ${sev.border}` }}
                            >
                              <div className="flex items-center gap-2 flex-wrap mb-1.5">
                                <span
                                  className="font-mono px-1.5 py-0.5 rounded text-xs"
                                  style={{ background: "var(--surface2)", color: "var(--lime)", border: "1px solid var(--border)" }}
                                >
                                  {issue.criterion}
                                </span>
                                <span className="font-semibold capitalize" style={{ color: sev.color }}>
                                  {issue.severity}
                                </span>
                              </div>
                              <p className="font-medium" style={{ color: "var(--text)" }}>{issue.description}</p>
                              {issue.examples && issue.examples.length > 0 && (
                                <ul className="mt-1.5 space-y-0.5" style={{ color: "var(--muted)" }}>
                                  {issue.examples.slice(0, 3).map((ex, i) => (
                                    <li key={i} className="font-mono truncate max-w-full">· {ex}</li>
                                  ))}
                                  {issue.examples.length > 3 && (
                                    <li className="italic">+ {issue.examples.length - 3} more</li>
                                  )}
                                </ul>
                              )}
                              {issue.fix && (
                                <p className="mt-1.5 italic" style={{ color: "var(--muted)" }}>
                                  Fix: {issue.fix}
                                </p>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {(ts.screenshot_b64 || ts.screenshot_path) && (
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-widest mb-2" style={{ color: "var(--muted)" }}>
                        Screenshot
                      </p>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={
                          ts.screenshot_b64
                            ? `data:image/png;base64,${ts.screenshot_b64}`
                            : `${API_BASE}/screenshots/${ts.screenshot_path!.split("/screenshots/")[1]}`
                        }
                        alt={`Screenshot from ${ts.test_name}`}
                        className="rounded-lg max-w-full"
                        style={{ border: "1px solid var(--border)" }}
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
