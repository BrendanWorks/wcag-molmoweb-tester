"use client";

export interface TestOption {
  id: string;
  label: string;
  description: string;
  wcag: string[];
  severity: "critical" | "high";
  phase: 1 | 2 | 3;
}

export const TEST_OPTIONS: TestOption[] = [
  {
    id: "keyboard_nav",
    label: "Keyboard Navigation",
    description: "Tabs through interactive elements; catches keyboard traps, inaccessible controls, and missing skip links.",
    wcag: ["2.1.1", "2.1.2", "2.4.1", "2.4.3"],
    severity: "critical",
    phase: 1,
  },
  {
    id: "focus_indicator",
    label: "Focus Visibility",
    description: "Molmo2 vision AI visually confirms each element has a visible focus ring — not just a CSS inspection.",
    wcag: ["2.4.7"],
    severity: "critical",
    phase: 2,
  },
  {
    id: "page_structure",
    label: "Page Structure & Semantics",
    description: "Alt text, headings, landmark regions, ARIA, duplicate IDs, language attribute, link text, and touch targets.",
    wcag: ["1.1.1", "1.3.1", "1.4.1", "2.2.2", "2.4.2", "2.4.4", "2.5.8", "3.1.1", "4.1.1", "4.1.2"],
    severity: "critical",
    phase: 1,
  },
  {
    id: "color_blindness",
    label: "Color & Contrast",
    description: "Applies a Deuteranopia simulation and walks the full DOM checking contrast ratios on every text node.",
    wcag: ["1.4.1", "1.4.3"],
    severity: "high",
    phase: 1,
  },
  {
    id: "zoom",
    label: "Resize Text & Reflow",
    description: "200% zoom via Chrome DevTools Protocol — checks for horizontal scroll and text clipped by overflow.",
    wcag: ["1.4.4", "1.4.10"],
    severity: "high",
    phase: 1,
  },
  {
    id: "form_errors",
    label: "Form Error Handling",
    description: "Submits invalid data and checks that error messages are descriptive, associated with inputs, and suggest corrections.",
    wcag: ["3.3.1", "3.3.2", "3.3.3"],
    severity: "high",
    phase: 2,
  },
];

function getVersionCriteria(test: TestOption, wcagVersion: "2.1" | "2.2"): string[] {
  if (test.id === "page_structure") {
    // 2.5.8 is WCAG 2.2 AA only; WCAG 2.1 AA has no touch-target requirement
    const base = test.wcag.filter((c) => c !== "2.5.8");
    return wcagVersion === "2.2" ? [...base, "2.5.8"] : base;
  }
  return test.wcag;
}

interface Props {
  selected: string[];
  onChange: (selected: string[]) => void;
  wcagVersion: "2.1" | "2.2";
}

export default function TestSelector({ selected, onChange, wcagVersion }: Props) {
  function toggle(id: string) {
    onChange(selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id]);
  }

  const allIds = TEST_OPTIONS.map((t) => t.id);

  return (
    <fieldset>
      <div className="flex items-center justify-between mb-3">
        <legend className="text-sm font-medium" style={{ color: "var(--text)" }}>
          Select Tests{" "}
          <span className="text-xs font-normal" style={{ color: "var(--muted)" }}>
            ({selected.length} of {TEST_OPTIONS.length} selected)
          </span>
        </legend>
        <div className="flex gap-3 text-xs" style={{ color: "var(--muted)" }}>
          <button
            type="button"
            onClick={() => onChange(allIds)}
            className="hover:opacity-80 transition-opacity"
            style={{ color: "var(--lime)" }}
          >
            Select all
          </button>
          <span style={{ color: "var(--border)" }}>|</span>
          <button
            type="button"
            onClick={() => onChange([])}
            className="hover:opacity-80 transition-opacity"
          >
            Deselect all
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {TEST_OPTIONS.map((test) => {
          const checked = selected.includes(test.id);
          const criteria = getVersionCriteria(test, wcagVersion);
          const isCritical = test.severity === "critical";

          return (
            <label
              key={test.id}
              className="flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-all"
              style={{
                background: checked ? "rgba(204,255,0,0.06)" : "var(--surface)",
                border: `1px solid ${checked ? "rgba(204,255,0,0.3)" : "var(--border)"}`,
              }}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggle(test.id)}
                className="mt-0.5 h-4 w-4 flex-shrink-0 rounded"
                style={{ accentColor: "var(--lime)" }}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2 mb-0.5">
                  <p
                    className="text-sm font-medium"
                    style={{ color: checked ? "var(--lime)" : "var(--text)" }}
                  >
                    {test.label}
                  </p>
                  <span
                    className="text-xs px-1.5 py-0.5 rounded font-semibold flex-shrink-0"
                    style={
                      isCritical
                        ? { background: "rgba(255,51,102,0.12)", color: "var(--crimson)" }
                        : { background: "rgba(255,184,0,0.12)", color: "var(--amber)" }
                    }
                  >
                    {isCritical ? "Critical" : "High"}
                  </span>
                </div>
                <p className="text-xs" style={{ color: "var(--muted)" }}>
                  {test.description}
                </p>
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {criteria.map((c) => (
                    <span
                      key={c}
                      className="inline-block text-xs rounded px-1.5 py-0.5 font-mono"
                      style={{
                        background: "var(--surface2)",
                        color: "var(--muted)",
                        border: "1px solid var(--border)",
                      }}
                    >
                      {c}
                    </span>
                  ))}
                </div>
              </div>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
