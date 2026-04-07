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

const SEVERITY_BADGE: Record<string, string> = {
  critical: "bg-red-100 text-red-700 border-red-200",
  major: "bg-orange-100 text-orange-700 border-orange-200",
  minor: "bg-yellow-100 text-yellow-700 border-yellow-200",
};

const RESULT_ICON: Record<string, string> = {
  pass: "✓",
  fail: "✗",
  warning: "⚠",
  error: "!",
};

const RESULT_COLOR: Record<string, string> = {
  pass: "text-green-700 bg-green-50 border-green-200",
  fail: "text-red-700 bg-red-50 border-red-200",
  warning: "text-yellow-700 bg-yellow-50 border-yellow-200",
  error: "text-orange-700 bg-orange-50 border-orange-200",
};

const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  compliant: { label: "Compliant", color: "text-green-700 bg-green-100" },
  issues_found: { label: "Issues Found", color: "text-orange-700 bg-orange-100" },
  critical_issues: { label: "Critical Issues", color: "text-red-700 bg-red-100" },
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function ResultsDashboard({
  report,
  url,
}: {
  report: Record<string, unknown>;
  url: string;
}) {
  const r = report as unknown as Report;
  const [expandedTest, setExpandedTest] = useState<string | null>(null);
  const status = STATUS_LABEL[r.overall_status] ?? STATUS_LABEL.issues_found;

  function downloadJson() {
    const blob = new Blob([JSON.stringify(r, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `wcag-report-${r.run_id?.slice(0, 8)}.json`;
    a.click();
  }

  function downloadCsv() {
    // Build CSV from already-available local report data (no server roundtrip needed)
    const rows = [
      ["Test", "Result", "Severity", "WCAG Criteria", "Failure Reason", "Recommendation"],
      ...(r.test_summaries ?? []).map((ts: TestSummary) => [
        ts.test_name,
        ts.result,
        ts.severity,
        ts.wcag_criteria.join("|"),
        ts.failure_reason,
        ts.recommendation,
      ]),
    ];
    const csv = rows.map((row) => row.map((v: unknown) => `"${String(v).replace(/"/g, "'")}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `wcag-report-${r.run_id?.slice(0, 8)}.csv`;
    a.click();
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white border border-slate-200 rounded-xl p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${status.color}`}>
                {status.label}
              </span>
            </div>
            <h2 className="text-xl font-bold text-slate-900 break-all">{url}</h2>
            <p className="text-xs text-slate-400 mt-1">
              Run ID: {r.run_id} · {new Date(r.generated_at).toLocaleString()}
            </p>
          </div>
          <div className="text-center">
            <p className="text-4xl font-bold text-slate-900">{r.compliance_percentage}%</p>
            <p className="text-xs text-slate-500">Compliance</p>
          </div>
        </div>

        {/* Summary counts */}
        <div className="grid grid-cols-4 gap-3 mt-5">
          {[
            { label: "Passed", value: r.summary.passed, color: "text-green-700 bg-green-50 border-green-200" },
            { label: "Failed", value: r.summary.failed, color: "text-red-700 bg-red-50 border-red-200" },
            { label: "Warnings", value: r.summary.warnings, color: "text-yellow-700 bg-yellow-50 border-yellow-200" },
            { label: "Total", value: r.summary.total_tests, color: "text-slate-700 bg-slate-50 border-slate-200" },
          ].map((s) => (
            <div key={s.label} className={`rounded-lg border p-3 text-center ${s.color}`}>
              <p className="text-2xl font-bold">{s.value}</p>
              <p className="text-xs font-medium">{s.label}</p>
            </div>
          ))}
        </div>

        {/* Download */}
        <div className="flex gap-3 mt-5">
          <button
            onClick={downloadJson}
            className="text-xs border border-slate-200 hover:border-slate-300 bg-white
                       text-slate-600 rounded-lg px-3 py-1.5 transition-colors
                       focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            Download JSON
          </button>
          <button
            onClick={downloadCsv}
            className="text-xs border border-slate-200 hover:border-slate-300 bg-white
                       text-slate-600 rounded-lg px-3 py-1.5 transition-colors
                       focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            Download CSV
          </button>
        </div>
      </div>

      {/* OLMo2 narrative */}
      {r.narrative && (
        <div className="bg-white border border-slate-200 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              AI Assessment
            </span>
            <span className="text-xs bg-blue-50 text-blue-600 border border-blue-100 rounded-full px-2 py-0.5 font-medium">
              OLMo2-7B
            </span>
          </div>
          <div className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">
            {r.narrative}
          </div>
        </div>
      )}

      {/* Top failing criteria */}
      {r.top_criteria_failures?.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Top Failing WCAG Criteria</h3>
          <div className="space-y-2">
            {r.top_criteria_failures.map((cf) => (
              <div key={cf.criterion} className="flex items-center gap-3">
                <span className="font-mono text-xs text-slate-500 w-12">{cf.criterion}</span>
                <span className="text-sm text-slate-700 flex-1">{cf.label}</span>
                <span className="text-xs font-semibold text-red-600">
                  {cf.failure_count}×
                </span>
                <div className="w-24 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                  <div
                    className="h-1.5 bg-red-400 rounded-full"
                    style={{
                      width: `${Math.min(100, (cf.failure_count / (r.summary.total_tests || 1)) * 100)}%`,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Per-test results */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-slate-700">Test Results</h3>
        {r.test_summaries?.map((ts) => (
          <div
            key={ts.test_id}
            className="bg-white border border-slate-200 rounded-xl overflow-hidden"
          >
            <button
              onClick={() => setExpandedTest(expandedTest === ts.test_id ? null : ts.test_id)}
              className="w-full flex items-center gap-3 p-4 text-left hover:bg-slate-50
                         focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500"
              aria-expanded={expandedTest === ts.test_id}
            >
              <span
                className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center
                             text-xs font-bold border ${RESULT_COLOR[ts.result] ?? RESULT_COLOR.warning}`}
              >
                {RESULT_ICON[ts.result] ?? "?"}
              </span>
              <span className="flex-1 font-medium text-sm text-slate-800">{ts.test_name}</span>
              {ts.severity && ts.result === "fail" && (
                <span
                  className={`text-xs px-2 py-0.5 rounded border font-medium
                               ${SEVERITY_BADGE[ts.severity] ?? SEVERITY_BADGE.minor}`}
                >
                  {ts.severity}
                </span>
              )}
              {ts.wcag_criteria?.map((c) => (
                <span key={c} className="hidden sm:inline text-xs font-mono bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded">
                  {c}
                </span>
              ))}
              <span className="text-slate-400 text-xs ml-1">
                {expandedTest === ts.test_id ? "▲" : "▼"}
              </span>
            </button>

            {expandedTest === ts.test_id && (
              <div className="border-t border-slate-100 p-4 space-y-3 text-sm">
                {ts.failure_reason && (
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                      Failure
                    </p>
                    <p className="text-slate-700">{ts.failure_reason}</p>
                  </div>
                )}
                {ts.recommendation && (
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                      Recommendation
                    </p>
                    <p className="text-slate-700">{ts.recommendation}</p>
                  </div>
                )}
                {ts.wcag_criteria?.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                      WCAG Criteria
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {ts.wcag_criteria.map((c) => (
                        <span key={c} className="font-mono text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">
                          {c}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {/* Molmo2 visual confirmation details (focus_indicator only) */}
                {ts.test_id === "focus_indicator" && ts.details && (
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                      Visual Confirmation
                    </p>
                    <div className="flex items-center gap-2 flex-wrap mb-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${
                        ts.details.molmo2_used
                          ? "bg-blue-50 text-blue-700 border-blue-200"
                          : "bg-slate-50 text-slate-500 border-slate-200"
                      }`}>
                        {ts.details.molmo2_used ? "Molmo2-4B" : "CSS only"}
                      </span>
                      {ts.details.tabs_tested !== undefined && (
                        <span className="text-xs text-slate-500">
                          {ts.details.tabs_tested} element{ts.details.tabs_tested !== 1 ? "s" : ""} checked
                        </span>
                      )}
                      {ts.details.failure_count !== undefined && ts.details.failure_count > 0 && (
                        <span className="text-xs text-red-600 font-medium">
                          {ts.details.failure_count} missing focus indicator{ts.details.failure_count !== 1 ? "s" : ""}
                        </span>
                      )}
                      {ts.details.molmo2_warnings !== undefined && ts.details.molmo2_warnings > 0 && (
                        <span className="text-xs text-yellow-600 font-medium">
                          {ts.details.molmo2_warnings} Molmo2 visual warning{ts.details.molmo2_warnings !== 1 ? "s" : ""}
                        </span>
                      )}
                    </div>
                    {/* Show Molmo2 pointing results for each step */}
                    {ts.details.steps && ts.details.steps.filter(
                      (s) => s.analysis.layer === "molmo2_visual"
                    ).slice(0, 15).map((step) => {
                      const found = !!step.analysis.molmo2_point;
                      const fi = step.focus_info;
                      return (
                        <div
                          key={step.tab}
                          className={`text-xs rounded p-2 mb-1 border ${
                            found
                              ? "bg-blue-50 border-blue-100"
                              : "bg-red-50 border-red-100"
                          }`}
                        >
                          <div className="flex items-center gap-1 flex-wrap">
                            <span className={`font-semibold ${found ? "text-blue-700" : "text-red-700"}`}>
                              Tab {step.tab}
                            </span>
                            <span className="text-slate-400">·</span>
                            <span className="text-slate-700 truncate max-w-[200px]">
                              {step.analysis.focused_element}
                            </span>
                            <span className="text-slate-400">·</span>
                            {found ? (
                              <span className="font-mono text-blue-600">
                                Molmo2 → ({step.analysis.molmo2_point!.x}, {step.analysis.molmo2_point!.y})px ✓
                              </span>
                            ) : (
                              <span className="font-mono text-red-600 font-semibold">
                                Molmo2 → not found ✗
                              </span>
                            )}
                          </div>
                          {/* Show expected DOM location when Molmo2 missed */}
                          {!found && fi && (
                            <div className="mt-1 flex items-center gap-2 text-slate-500">
                              <span className="text-red-400">↳</span>
                              <span>
                                Expected at{" "}
                                <span className="font-mono text-slate-600">
                                  ({Math.round(fi.x)}, {Math.round(fi.y)})
                                </span>
                                {" "}—{" "}
                                <span className="font-mono text-slate-600">
                                  {Math.round(fi.width)}×{Math.round(fi.height)}px
                                </span>
                              </span>
                              {step.analysis.css_indicator && (
                                <span className="text-slate-400 truncate">
                                  · {step.analysis.css_indicator}
                                </span>
                              )}
                            </div>
                          )}
                          {/* Show CSS indicator for confirmed hits */}
                          {found && step.analysis.css_indicator && (
                            <div className="mt-0.5 text-slate-400 truncate">
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
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                      Issues Found
                    </p>
                    <div className="flex items-center gap-3 flex-wrap mb-2 text-xs">
                      {ts.details.critical_count !== undefined && ts.details.critical_count > 0 && (
                        <span className="text-red-600 font-medium">{ts.details.critical_count} critical</span>
                      )}
                      {ts.details.major_count !== undefined && ts.details.major_count > 0 && (
                        <span className="text-orange-600 font-medium">{ts.details.major_count} major</span>
                      )}
                      {ts.details.minor_count !== undefined && ts.details.minor_count > 0 && (
                        <span className="text-yellow-600 font-medium">{ts.details.minor_count} minor</span>
                      )}
                    </div>
                    <div className="space-y-2">
                      {ts.details.issues.map((issue, idx) => (
                        <div
                          key={idx}
                          className={`rounded-lg border p-3 text-xs ${
                            issue.severity === "critical"
                              ? "bg-red-50 border-red-200"
                              : issue.severity === "major"
                              ? "bg-orange-50 border-orange-200"
                              : "bg-yellow-50 border-yellow-200"
                          }`}
                        >
                          <div className="flex items-center gap-2 flex-wrap mb-1">
                            <span className="font-mono bg-white border border-slate-200 text-slate-600 px-1.5 py-0.5 rounded">
                              {issue.criterion}
                            </span>
                            <span className={`font-semibold capitalize ${
                              issue.severity === "critical"
                                ? "text-red-700"
                                : issue.severity === "major"
                                ? "text-orange-700"
                                : "text-yellow-700"
                            }`}>
                              {issue.severity}
                            </span>
                          </div>
                          <p className="text-slate-800 font-medium">{issue.description}</p>
                          {issue.examples && issue.examples.length > 0 && (
                            <ul className="mt-1.5 space-y-0.5 text-slate-600">
                              {issue.examples.slice(0, 3).map((ex, i) => (
                                <li key={i} className="font-mono truncate max-w-full">
                                  · {ex}
                                </li>
                              ))}
                              {issue.examples.length > 3 && (
                                <li className="text-slate-400 italic">
                                  + {issue.examples.length - 3} more
                                </li>
                              )}
                            </ul>
                          )}
                          {issue.fix && (
                            <p className="mt-1.5 text-slate-500 italic">Fix: {issue.fix}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {(ts.screenshot_b64 || ts.screenshot_path) && (
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
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
                      className="rounded border border-slate-200 max-w-full"
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
