/* Thin wrapper around gtag so we get type safety and a single import site. */

declare function gtag(command: "event", action: string, params?: Record<string, unknown>): void;

function fire(action: string, params?: Record<string, unknown>) {
  if (typeof window === "undefined") return;
  if (typeof (window as unknown as { gtag?: unknown }).gtag !== "function") return;
  gtag("event", action, params);
}

export const analytics = {
  auditStarted(url: string, tests: string[], wcagVersion: string) {
    fire("audit_started", { url, test_count: tests.length, wcag_version: wcagVersion });
  },

  auditCompleted(opts: {
    url: string;
    wcagVersion: string;
    passed: number;
    failed: number;
    warnings: number;
    compliancePct: number;
  }) {
    fire("audit_completed", {
      url: opts.url,
      wcag_version: opts.wcagVersion,
      passed: opts.passed,
      failed: opts.failed,
      warnings: opts.warnings,
      compliance_pct: opts.compliancePct,
    });
  },

  reportDownloaded(format: "pdf" | "csv" | "json") {
    fire("report_downloaded", { format });
  },

  wcagVersionSelected(version: "2.1" | "2.2") {
    fire("wcag_version_selected", { version });
  },

  auditCancelled(url: string) {
    fire("audit_cancelled", { url });
  },

  auditError(url: string, message: string) {
    fire("audit_error", { url, error_message: message });
  },
};
