import jsPDF from "jspdf";

// ── Types ─────────────────────────────────────────────────────────────────────
interface StructureIssue {
  criterion: string;
  severity: string;
  description: string;
  examples?: string[];
  fix?: string;
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
    molmo2_point?: { x: number; y: number };
    failure_reason?: string;
  };
}

interface TestDetails {
  molmo2_used?: boolean;
  molmo2_warnings?: number;
  steps?: FocusStep[];
  tabs_tested?: number;
  failure_count?: number;
  issues?: StructureIssue[];
  critical_count?: number;
  serious_count?: number;
  moderate_count?: number;
  minor_count?: number;
  /** legacy field from pre-rename jobs */
  major_count?: number;
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
  wcag_version?: string;
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

// ── Confidence tier ───────────────────────────────────────────────────────────
type ConfidenceTier = "high" | "medium" | "low";

function getConfidenceTier(ts: TestSummary): ConfidenceTier {
  const d = ts.details ?? {};
  switch (ts.test_id) {
    case "page_structure": return "high";
    case "zoom":           return "high";
    case "focus_indicator":
      if ((d.tabs_tested ?? 0) < 3) return "low";
      if (d.molmo2_used) return "high";
      return "medium";
    case "keyboard_nav":
      if ((d.tabs_tested ?? 0) >= 5) return "high";
      if ((d.tabs_tested ?? 0) >= 2) return "medium";
      return "low";
    case "color_blindness":
      return ts.result === "pass" ? "high" : "medium";
    default:
      return "medium";
  }
}

// ── Brand colors ──────────────────────────────────────────────────────────────
type RGB = [number, number, number];
const BG:       RGB = [26,  26,  27];
const SURFACE:  RGB = [32,  32,  34];
const SURFACE2: RGB = [42,  42,  44];
const BORDER:   RGB = [48,  48,  51];
const LIME:     RGB = [204, 255, 0];
const CRIMSON:  RGB = [255, 51,  102];
const AMBER:    RGB = [255, 184, 0];
const TEXT:     RGB = [239, 239, 239];
const MUTED:    RGB = [144, 144, 153];
const ORANGE:   RGB = [255, 120, 0];
const TEAL:     RGB = [110, 231, 183]; // high confidence

// Confidence tier colors: [fg, bg, border]
const CONF_COLORS: Record<ConfidenceTier, { fg: RGB; bg: RGB; bd: RGB; label: string }> = {
  high:   { fg: TEAL,   bg: [15, 40, 25],  bd: [40, 90, 60],  label: "* high" },
  medium: { fg: MUTED,  bg: SURFACE2,      bd: BORDER,         label: "~ med"  },
  low:    { fg: AMBER,  bg: [25, 18, 0],   bd: [70, 50, 0],    label: "o low"  },
};

// Status badge colors
const STATUS_COLORS: Record<string, { fg: RGB; bg: RGB; label: string }> = {
  compliant:       { fg: LIME,    bg: [12, 25, 0],  label: "Compliant"       },
  issues_found:    { fg: AMBER,   bg: [25, 18, 0],  label: "Issues Found"    },
  critical_issues: { fg: CRIMSON, bg: [25, 5, 10],  label: "Critical Issues" },
};

// ── Page layout ───────────────────────────────────────────────────────────────
const PW = 210;
const PH = 297;
const ML = 14;
const MR = 14;
const CW = PW - ML - MR;
const FOOTER_H = 9;

// ── Character sanitizer ───────────────────────────────────────────────────────
// jsPDF's built-in Helvetica only covers Latin-1. Non-Latin-1 characters cause
// encoding artifacts or trigger a monospace font fallback. Normalize everything
// to safe ASCII equivalents before passing to jsPDF.
function sanitize(text: string): string {
  return (text ?? "")
    .replace(/\u2018|\u2019/g, "'")   // curly single quotes
    .replace(/\u201C|\u201D/g, '"')   // curly double quotes
    .replace(/\u2013/g, "-")          // en dash
    .replace(/\u2014/g, "-")          // em dash
    .replace(/\u2026/g, "...")        // ellipsis
    .replace(/\u2265/g, ">=")         // ≥
    .replace(/\u2264/g, "<=")         // ≤
    .replace(/\u00B1/g, "+/-")        // ±
    .replace(/\u00D7/g, "x")          // ×
    .replace(/\u2192/g, "->")         // →
    .replace(/\u2022/g, "*")          // •
    .replace(/\u00A0/g, " ")          // non-breaking space
    .replace(/[^\x00-\xFF]/g, "?");   // any remaining non-Latin-1
}

export function generatePdf(report: Record<string, unknown>): void {
  const r = report as unknown as Report;
  const wcagLabel = `WCAG ${r.wcag_version ?? "2.2"} Level AA`;
  const doc = new jsPDF({ unit: "mm", format: "a4", compress: true });

  let y = 0;

  // ── Page utilities ────────────────────────────────────────────────────────────
  function fillPageBg() {
    doc.setFillColor(BG[0], BG[1], BG[2]);
    doc.rect(0, 0, PW, PH, "F");
  }

  function newPage() {
    doc.addPage();
    fillPageBg();
    y = 14;
  }

  function checkSpace(needed: number) {
    if (y + needed > PH - FOOTER_H - 4) newPage();
  }

  // ── Draw helpers ──────────────────────────────────────────────────────────────
  function fill(rgb: RGB)  { doc.setFillColor(rgb[0], rgb[1], rgb[2]); }
  function drawC(rgb: RGB) { doc.setDrawColor(rgb[0], rgb[1], rgb[2]); }
  function textC(rgb: RGB) { doc.setTextColor(rgb[0], rgb[1], rgb[2]); }

  function rRect(
    x: number, ry: number, w: number, h: number,
    fillRgb?: RGB, strokeRgb?: RGB, radius = 2,
  ) {
    if (fillRgb) fill(fillRgb);
    if (strokeRgb) {
      drawC(strokeRgb);
      doc.roundedRect(x, ry, w, h, radius, radius, fillRgb ? "FD" : "D");
    } else if (fillRgb) {
      doc.roundedRect(x, ry, w, h, radius, radius, "F");
    }
  }

  // Draw a pill badge; returns x position after the pill (for chaining)
  function pill(
    label: string, x: number, ty: number,
    bg: RGB, fg: RGB, bd: RGB, size = 7,
  ): number {
    doc.setFontSize(size);
    doc.setFont("helvetica", "bold");
    const tw = doc.getTextWidth(label);
    const pw = tw + 4;
    const ph = size * 0.353 * 1.9;
    rRect(x, ty - ph * 0.73, pw, ph, bg, bd, 1.5);
    textC(fg);
    doc.text(label, x + 2, ty);
    return x + pw + 2;
  }

  // Draw section header label
  function sectionLabel(label: string) {
    checkSpace(10);
    doc.setFontSize(7.5);
    doc.setFont("helvetica", "bold");
    textC(MUTED);
    doc.text(label, ML, y);
    y += 5;
  }

  // ── PAGE 1: HEADER BAND ───────────────────────────────────────────────────────
  fillPageBg();

  doc.setFillColor(SURFACE[0], SURFACE[1], SURFACE[2]);
  doc.rect(0, 0, PW, 44, "F");
  doc.setFillColor(LIME[0], LIME[1], LIME[2]);
  doc.rect(0, 0, 4, 44, "F");

  doc.setFontSize(20);
  doc.setFont("helvetica", "bold");
  textC(LIME);
  doc.text("PointCheck", ML + 5, 14);

  doc.setFontSize(8.5);
  doc.setFont("helvetica", "normal");
  textC(MUTED);
  doc.text(`${wcagLabel} Accessibility Report`, ML + 5, 21);

  const urlDisplay = sanitize(
    (r.url?.length ?? 0) > 68 ? r.url.slice(0, 65) + "..." : (r.url ?? "")
  );
  doc.setFontSize(9.5);
  doc.setFont("helvetica", "bold");
  textC(TEXT);
  doc.text(urlDisplay, ML + 5, 30);

  const dateStr = r.generated_at ? new Date(r.generated_at).toLocaleString() : "";
  doc.setFontSize(7.5);
  doc.setFont("helvetica", "normal");
  textC(MUTED);
  doc.text(sanitize(`${dateStr}  -  ${r.run_id ?? ""}`), ML + 5, 38);

  y = 52;

  // ── COMPLIANCE OVERVIEW ───────────────────────────────────────────────────────
  checkSpace(46);

  const compRgb: RGB =
    r.compliance_percentage >= 80 ? LIME :
    r.compliance_percentage >= 50 ? AMBER : CRIMSON;

  doc.setFontSize(44);
  doc.setFont("helvetica", "bold");
  textC(compRgb);
  doc.text(`${r.compliance_percentage}%`, ML, y + 14);

  doc.setFontSize(8);
  doc.setFont("helvetica", "normal");
  textC(MUTED);
  doc.text("Compliance", ML, y + 20);

  // Overall status badge — matches the pill shown in the UI header
  const statusEntry = STATUS_COLORS[r.overall_status] ?? STATUS_COLORS.issues_found;
  pill(sanitize(statusEntry.label), ML, y + 25, statusEntry.bg, statusEntry.fg, statusEntry.fg, 7.5);

  y += 34;

  // Summary counts — 4 boxes matching UI order: Passed / Failed / Warnings / Total
  const counts: Array<{ label: string; value: number; fg: RGB; bg: RGB; bd: RGB }> = [
    { label: "Passed",   value: r.summary?.passed      ?? 0, fg: LIME,    bg: [12,25,0],  bd: [35,70,0]  },
    { label: "Failed",   value: r.summary?.failed      ?? 0, fg: CRIMSON, bg: [25,5,10],  bd: [70,15,25] },
    { label: "Warnings", value: r.summary?.warnings    ?? 0, fg: AMBER,   bg: [25,18,0],  bd: [70,50,0]  },
    { label: "Total",    value: r.summary?.total_tests ?? 0, fg: TEXT,    bg: SURFACE2,   bd: BORDER     },
  ];
  const boxW = (CW - 9) / 4;
  counts.forEach((ct, i) => {
    const bx = ML + i * (boxW + 3);
    rRect(bx, y, boxW, 17, ct.bg, ct.bd);
    doc.setFontSize(20);
    doc.setFont("helvetica", "bold");
    textC(ct.fg);
    doc.text(String(ct.value), bx + boxW / 2, y + 11, { align: "center" });
    doc.setFontSize(7);
    doc.setFont("helvetica", "normal");
    textC(MUTED);
    doc.text(ct.label, bx + boxW / 2, y + 15.5, { align: "center" });
  });

  y += 25;

  // ── TEST OVERVIEW TABLE ───────────────────────────────────────────────────────
  const tests = r.test_summaries ?? [];
  if (tests.length > 0) {
    sectionLabel("TEST OVERVIEW");

    const RESULT_FG: Record<string, RGB> = {
      pass: LIME, fail: CRIMSON, warning: AMBER, error: ORANGE,
    };
    const RESULT_BG: Record<string, RGB> = {
      pass: [12,25,0], fail: [25,5,10], warning: [25,18,0], error: [25,12,0],
    };
    const RESULT_BD: Record<string, RGB> = {
      pass: [35,70,0], fail: [70,15,25], warning: [70,50,0], error: [70,35,0],
    };
    // ASCII result labels (no Unicode)
    const RESULT_LABEL: Record<string, string> = {
      pass: "PASS", fail: "FAIL", warning: "WARN", error: "ERR",
    };

    const rowH = 9;
    const tableH = tests.length * rowH + 2;
    checkSpace(tableH);

    tests.forEach((ts, i) => {
      const ry = y + i * rowH;
      // Alternating row tint
      if (i % 2 === 0) {
        fill(SURFACE);
        doc.rect(ML, ry, CW, rowH, "F");
      }
      // Result badge
      const fg = RESULT_FG[ts.result] ?? AMBER;
      const bg = RESULT_BG[ts.result] ?? ([25,18,0] as RGB);
      const bd = RESULT_BD[ts.result] ?? ([70,50,0] as RGB);
      const rlabel = RESULT_LABEL[ts.result] ?? "WARN";
      pill(rlabel, ML + 2, ry + 6, bg, fg, bd, 6.5);

      // Test name
      doc.setFontSize(8.5);
      doc.setFont("helvetica", "normal");
      textC(TEXT);
      doc.text(sanitize(ts.test_name), ML + 22, ry + 6);

      // WCAG criteria (right-aligned, muted)
      doc.setFontSize(7);
      doc.setFont("helvetica", "normal");
      textC(MUTED);
      const crit = (ts.wcag_criteria ?? []).join("  ");
      doc.text(sanitize(crit), ML + CW - 2, ry + 6, { align: "right" });
    });

    // Bottom border on table
    drawC(BORDER);
    doc.line(ML, y + tableH - 2, ML + CW, y + tableH - 2);

    y += tableH + 8;
  }

  // ── EXECUTIVE SUMMARY ─────────────────────────────────────────────────────────
  if (r.narrative) {
    sectionLabel("AI ASSESSMENT");
    y -= 5; // sectionLabel already advanced y by 5; we want the badge on the same line
    pill("OLMo3-7B", ML + 36, y - 1, [12,25,0], LIME, [35,70,0], 7);
    y += 5;

    doc.setFontSize(8.5);
    const narLines = doc.splitTextToSize(sanitize(r.narrative), CW - 10);
    const narBoxH = narLines.length * 4.2 + 10;

    checkSpace(narBoxH);
    rRect(ML, y, CW, narBoxH, SURFACE, BORDER);
    doc.setFont("helvetica", "normal");
    textC(TEXT);
    doc.text(narLines, ML + 5, y + 6);
    y += narBoxH + 8;
  }

  // ── TOP FAILING CRITERIA ──────────────────────────────────────────────────────
  if ((r.top_criteria_failures?.length ?? 0) > 0) {
    sectionLabel("TOP FAILING WCAG CRITERIA");

    for (const cf of r.top_criteria_failures) {
      checkSpace(7);
      doc.setFontSize(8);
      doc.setFont("helvetica", "bold");
      textC(MUTED);
      doc.text(sanitize(cf.criterion), ML, y);
      doc.setFont("helvetica", "normal");
      textC(TEXT);
      doc.text(sanitize(cf.label), ML + 15, y);
      textC(CRIMSON);
      doc.text(`${cf.failure_count}x`, ML + CW, y, { align: "right" });
      const barW = 22;
      const barX = ML + CW - barW - 8;
      rRect(barX, y - 2.5, barW, 2, SURFACE2, SURFACE2, 1);
      const fillW = Math.min(barW, (cf.failure_count / Math.max(r.summary?.total_tests ?? 1, 1)) * barW * 3);
      fill(CRIMSON);
      doc.roundedRect(barX, y - 2.5, fillW, 2, 1, 1, "F");
      y += 6;
    }
    y += 5;
  }

  // ── PER-TEST RESULTS ──────────────────────────────────────────────────────────
  sectionLabel("TEST RESULTS");

  const RESULT_C: Record<string, { fg: RGB; bg: RGB; bd: RGB }> = {
    pass:    { fg: LIME,    bg: [12,25,0],  bd: [35,70,0]  },
    fail:    { fg: CRIMSON, bg: [25,5,10],  bd: [70,15,25] },
    warning: { fg: AMBER,   bg: [25,18,0],  bd: [70,50,0]  },
    error:   { fg: ORANGE,  bg: [25,12,0],  bd: [70,35,0]  },
  };
  // ASCII-safe result icons (no Unicode symbols that corrupt in Helvetica)
  const RESULT_ICON: Record<string, string> = {
    pass: "P", fail: "F", warning: "W", error: "E",
  };
  const SEV_C: Record<string, { fg: RGB; bg: RGB; bd: RGB }> = {
    critical: { fg: CRIMSON,         bg: [25,5,10],  bd: [70,15,25] },
    serious:  { fg: [255,100,0],     bg: [25,10,0],  bd: [70,30,0]  },
    moderate: { fg: AMBER,           bg: [25,18,0],  bd: [70,50,0]  },
    minor:    { fg: [150,150,150],   bg: [18,18,18], bd: [60,60,60] },
    // legacy alias
    major:    { fg: [255,100,0],     bg: [25,10,0],  bd: [70,30,0]  },
  };
  const IMG_W = CW - 16;
  const IMG_H = IMG_W / (16 / 9);

  for (const ts of tests) {
    const rc = RESULT_C[ts.result] ?? RESULT_C.warning;
    const critFg: RGB = rc.fg;
    const critBd: RGB = rc.bd;
    const tier = getConfidenceTier(ts);
    const cc = CONF_COLORS[tier];

    // Pre-split text for accurate card height calculation
    doc.setFontSize(8.5);
    doc.setFont("helvetica", "normal");
    const frText  = sanitize(ts.failure_reason  ?? "");
    const recText = sanitize(ts.recommendation  ?? "");
    const frLines  = frText  ? doc.splitTextToSize(frText,  CW - 22) : [];
    const recLines = recText ? doc.splitTextToSize(recText, CW - 22) : [];

    // Pre-calculate extra height for focus_indicator detail
    const focusSteps = ts.test_id === "focus_indicator" && ts.details?.steps
      ? ts.details.steps.filter((s: FocusStep) => s.analysis.layer === "molmo2_visual").slice(0, 15)
      : [];
    const hasFocusDetail = ts.test_id === "focus_indicator" && ts.details != null;
    const focusDetailH = hasFocusDetail ? 12 + focusSteps.length * 7 + 4 : 0;

    // Pre-calculate extra height for page_structure issue detail
    const structIssues: StructureIssue[] = ts.test_id === "page_structure" && ts.details?.issues
      ? (ts.details.issues as StructureIssue[])
      : [];
    let structDetailH = 0;
    if (structIssues.length > 0) {
      structDetailH = 10; // section label + summary counts
      for (const issue of structIssues) {
        const descLines = doc.splitTextToSize(sanitize(issue.description ?? ""), CW - 28);
        structDetailH += 5 + descLines.length * 4.2;
        structDetailH += Math.min(3, issue.examples?.length ?? 0) * 4;
        if (issue.fix) structDetailH += 4.5;
        structDetailH += 5; // padding between issues
      }
    }

    let cardH = 7 + 12;
    if ((ts.wcag_criteria?.length ?? 0) > 0) cardH += 8;
    if (frLines.length > 0)   cardH += 5 + frLines.length  * 4.2 + 3;
    if (recLines.length > 0)  cardH += 5 + recLines.length * 4.2 + 3;
    cardH += focusDetailH + structDetailH;
    if (ts.screenshot_b64)    cardH += IMG_H + 4;
    cardH += 5;

    checkSpace(cardH);

    rRect(ML, y, CW, cardH, SURFACE, BORDER);

    let cy = y + 7;

    // Result icon circle
    fill(rc.bg);
    drawC(rc.bd);
    doc.circle(ML + 8, cy - 0.5, 3, "FD");
    doc.setFontSize(6.5);
    doc.setFont("helvetica", "bold");
    textC(rc.fg);
    doc.text(RESULT_ICON[ts.result] ?? "?", ML + 8, cy + 1.2, { align: "center" });

    // Test name
    doc.setFontSize(9.5);
    doc.setFont("helvetica", "bold");
    textC(TEXT);
    doc.text(sanitize(ts.test_name), ML + 14, cy + 1);

    // Severity badge (if fail)
    let badgeX = ML + 14;
    if (ts.result === "fail" && ts.severity && SEV_C[ts.severity]) {
      const sc = SEV_C[ts.severity];
      doc.setFontSize(9.5);
      const nameW = doc.getTextWidth(sanitize(ts.test_name));
      badgeX = pill(sanitize(ts.severity), ML + 14 + nameW + 3, cy + 1.5, sc.bg, sc.fg, sc.bd, 7);
    }
    // Confidence tier badge — right-justified, matching UI
    const confLabel = cc.label;
    doc.setFontSize(7);
    const confW = doc.getTextWidth(confLabel) + 4;
    const confX = ML + CW - confW - 2;
    if (confX > badgeX + 4) {
      rRect(confX, cy - 2.5, confW, 4.5, cc.bg, cc.bd, 1);
      textC(cc.fg);
      doc.text(confLabel, confX + 2, cy + 0.5);
    }

    cy += 11;

    // WCAG criteria pills — lime colored (matching expanded UI view)
    if ((ts.wcag_criteria?.length ?? 0) > 0) {
      let px = ML + 8;
      for (const c of ts.wcag_criteria) {
        doc.setFontSize(6.5);
        doc.setFont("helvetica", "normal");
        const tw = doc.getTextWidth(c);
        const pw = tw + 4;
        if (px + pw > ML + CW - 8) break;
        rRect(px, cy - 3, pw, 4.5, SURFACE2, critBd, 1);
        textC(critFg);
        doc.text(c, px + 2, cy);
        px += pw + 2;
      }
      cy += 7;
    }

    // Failure reason
    if (frLines.length > 0) {
      doc.setFontSize(7);
      doc.setFont("helvetica", "bold");
      textC(MUTED);
      doc.text("FAILURE", ML + 8, cy);
      cy += 4.5;
      doc.setFontSize(8.5);
      doc.setFont("helvetica", "normal");
      textC(TEXT);
      doc.text(frLines, ML + 8, cy);
      cy += frLines.length * 4.2 + 3;
    }

    // Recommendation
    if (recLines.length > 0) {
      doc.setFontSize(7);
      doc.setFont("helvetica", "bold");
      textC(MUTED);
      doc.text("RECOMMENDATION", ML + 8, cy);
      cy += 4.5;
      doc.setFontSize(8.5);
      doc.setFont("helvetica", "normal");
      textC(TEXT);
      doc.text(recLines, ML + 8, cy);
      cy += recLines.length * 4.2 + 3;
    }

    // ── Focus indicator: Visual Confirmation detail ───────────────────────────
    if (hasFocusDetail && ts.details) {
      const d = ts.details;
      doc.setFontSize(7);
      doc.setFont("helvetica", "bold");
      textC(MUTED);
      doc.text("VISUAL CONFIRMATION", ML + 8, cy);
      cy += 5;

      // Method + counts row
      const methodLabel = d.molmo2_used ? "MolmoWeb-8B" : "CSS only";
      const methodFg: RGB = d.molmo2_used ? LIME : MUTED;
      const methodBg: RGB = d.molmo2_used ? [12, 25, 0] : SURFACE2;
      const methodBd: RGB = d.molmo2_used ? [35, 70, 0] : BORDER;
      let mx = pill(methodLabel, ML + 8, cy, methodBg, methodFg, methodBd, 6.5);
      if (d.tabs_tested !== undefined) {
        doc.setFontSize(6.5);
        doc.setFont("helvetica", "normal");
        textC(MUTED);
        doc.text(`${d.tabs_tested} elem checked`, mx + 1, cy);
        mx += doc.getTextWidth(`${d.tabs_tested} elem checked`) + 4;
      }
      if (d.failure_count && (d.failure_count as number) > 0) {
        doc.setFontSize(6.5);
        doc.setFont("helvetica", "normal");
        textC(CRIMSON);
        doc.text(`${d.failure_count} missing`, mx + 1, cy);
      }
      cy += 6;

      // Per-step rows (molmo2_visual layer only, up to 15)
      for (const step of focusSteps) {
        const found = !!step.analysis.molmo2_point;
        const rowFg: RGB  = found ? LIME : CRIMSON;
        const rowBg: RGB  = found ? [10, 20, 5] : [20, 5, 8];
        const rowBd: RGB  = found ? [30, 60, 10] : [60, 15, 20];
        rRect(ML + 8, cy - 3.5, CW - 16, 6, rowBg, rowBd, 1);
        doc.setFontSize(6.5);
        doc.setFont("helvetica", "bold");
        textC(rowFg);
        doc.text(`Tab ${step.tab}`, ML + 10, cy);
        doc.setFont("helvetica", "normal");
        textC(TEXT);
        const elemText = sanitize(step.analysis.focused_element ?? "").slice(0, 40);
        doc.text(elemText, ML + 22, cy);
        if (found && step.analysis.molmo2_point) {
          textC(LIME);
          doc.text(`(${step.analysis.molmo2_point.x},${step.analysis.molmo2_point.y})px`, ML + CW - 18, cy, { align: "right" });
        } else {
          textC(CRIMSON);
          doc.text("not found", ML + CW - 18, cy, { align: "right" });
        }
        cy += 7;
      }
      cy += 2;
    }

    // ── Page structure: Issues Found detail ───────────────────────────────────
    if (structIssues.length > 0 && ts.details) {
      const d = ts.details;
      doc.setFontSize(7);
      doc.setFont("helvetica", "bold");
      textC(MUTED);
      doc.text("ISSUES FOUND", ML + 8, cy);
      cy += 4.5;

      // Severity counts summary
      let scx = ML + 8;
      if (d.critical_count && (d.critical_count as number) > 0) {
        doc.setFontSize(6.5);
        doc.setFont("helvetica", "normal");
        textC(CRIMSON);
        doc.text(`${d.critical_count} critical`, scx, cy);
        scx += doc.getTextWidth(`${d.critical_count} critical`) + 5;
      }
      const seriousCount = (d.serious_count ?? d.major_count ?? 0) as number;
      if (seriousCount > 0) {
        doc.setFontSize(6.5);
        doc.setFont("helvetica", "normal");
        textC([255, 100, 0]);
        doc.text(`${seriousCount} serious`, scx, cy);
        scx += doc.getTextWidth(`${seriousCount} serious`) + 5;
      }
      if (d.moderate_count && (d.moderate_count as number) > 0) {
        doc.setFontSize(6.5);
        doc.setFont("helvetica", "normal");
        textC(AMBER);
        doc.text(`${d.moderate_count} moderate`, scx, cy);
        scx += doc.getTextWidth(`${d.moderate_count} moderate`) + 5;
      }
      if (d.minor_count && (d.minor_count as number) > 0) {
        doc.setFontSize(6.5);
        doc.setFont("helvetica", "normal");
        textC([150, 150, 150]);
        doc.text(`${d.minor_count} minor`, scx, cy);
      }
      cy += 6;

      // Individual issue blocks
      for (const issue of structIssues) {
        const sevColors = SEV_C[issue.severity] ?? SEV_C.minor;
        const issueDescLines = doc.splitTextToSize(sanitize(issue.description ?? ""), CW - 28);
        const issueH = 5 + issueDescLines.length * 4.2
          + Math.min(3, issue.examples?.length ?? 0) * 4
          + (issue.fix ? 4.5 : 0) + 4;
        rRect(ML + 8, cy - 1, CW - 16, issueH, sevColors.bg, sevColors.bd, 1.5);

        // Criterion pill + severity label
        let ipx = ML + 10;
        doc.setFontSize(6.5);
        const critW = doc.getTextWidth(issue.criterion) + 4;
        rRect(ipx, cy + 0.5, critW, 4.5, SURFACE2, BORDER, 1);
        textC(LIME);
        doc.text(issue.criterion, ipx + 2, cy + 3.5);
        ipx += critW + 3;
        doc.setFont("helvetica", "bold");
        textC(sevColors.fg);
        doc.text(sanitize(issue.severity), ipx, cy + 3.5);
        cy += 7;

        // Description
        doc.setFontSize(8);
        doc.setFont("helvetica", "normal");
        textC(TEXT);
        doc.text(issueDescLines, ML + 10, cy);
        cy += issueDescLines.length * 4.2;

        // Examples (up to 3)
        if (issue.examples && issue.examples.length > 0) {
          const exShown = issue.examples.slice(0, 3);
          for (const ex of exShown) {
            doc.setFontSize(6.5);
            doc.setFont("helvetica", "normal");
            textC(MUTED);
            const exText = sanitize(`· ${ex}`).slice(0, 80);
            doc.text(exText, ML + 10, cy);
            cy += 4;
          }
          if (issue.examples.length > 3) {
            textC(MUTED);
            doc.text(`+ ${issue.examples.length - 3} more`, ML + 10, cy);
            cy += 4;
          }
        }

        // Fix hint
        if (issue.fix) {
          doc.setFontSize(6.5);
          doc.setFont("helvetica", "italic");
          textC(MUTED);
          doc.text(sanitize(`Fix: ${issue.fix}`).slice(0, 90), ML + 10, cy);
          cy += 4.5;
        }

        cy += 3; // spacing between issues
      }
    }

    // Screenshot
    if (ts.screenshot_b64) {
      try {
        drawC(BORDER);
        doc.rect(ML + 8, cy, IMG_W, IMG_H, "D");
        doc.addImage(
          `data:image/png;base64,${ts.screenshot_b64}`,
          "PNG", ML + 8, cy, IMG_W, IMG_H,
        );
      } catch {
        // skip silently if image embedding fails
      }
    }

    y += cardH + 4;
  }

  // ── Footer on every page ──────────────────────────────────────────────────────
  const totalPages = doc.getNumberOfPages();
  for (let p = 1; p <= totalPages; p++) {
    doc.setPage(p);
    doc.setFillColor(SURFACE[0], SURFACE[1], SURFACE[2]);
    doc.rect(0, PH - FOOTER_H, PW, FOOTER_H, "F");
    doc.setDrawColor(BORDER[0], BORDER[1], BORDER[2]);
    doc.line(0, PH - FOOTER_H, PW, PH - FOOTER_H);
    doc.setFontSize(7);
    doc.setFont("helvetica", "normal");
    textC(MUTED);
    doc.text("pointcheck.org", ML, PH - 3);
    doc.text(wcagLabel, PW / 2, PH - 3, { align: "center" });
    doc.text(`${p} / ${totalPages}`, PW - MR, PH - 3, { align: "right" });
  }

  // ── Download ──────────────────────────────────────────────────────────────────
  // Filename: domainmmddyyyy  e.g. weinsteinau_04112026
  const hostname = (() => {
    try { return new URL(r.url).hostname; } catch { return r.url ?? "report"; }
  })();
  const domainNoTld = hostname.replace(/^www\./, "").replace(/\.[^.]+$/, "");
  const d = r.generated_at ? new Date(r.generated_at) : new Date();
  const mm   = String(d.getMonth() + 1).padStart(2, "0");
  const dd   = String(d.getDate()).padStart(2, "0");
  const yyyy = String(d.getFullYear());
  doc.save(`${domainNoTld}_${mm}${dd}${yyyy}.pdf`);
}
