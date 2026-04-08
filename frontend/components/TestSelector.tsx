"use client";

export interface TestOption {
  id: string;
  label: string;
  description: string;
  wcag: string[];
  phase: 1 | 2 | 3;
}

export const TEST_OPTIONS: TestOption[] = [
  {
    id: "keyboard_nav",
    label: "Keyboard-Only Navigation",
    description: "Tabs through interactive elements; checks every control is reachable and no keyboard traps exist.",
    wcag: ["2.1.1", "2.1.2", "2.4.3"],
    phase: 1,
  },
  {
    id: "zoom",
    label: "200% Zoom / Reflow",
    description: "Applies 2× browser zoom and checks that text, controls, and layout remain usable without horizontal scroll.",
    wcag: ["1.4.4", "1.4.10"],
    phase: 1,
  },
  {
    id: "color_blindness",
    label: "Color-Blindness Simulation",
    description: "Injects a Deuteranopia filter and checks whether any element can only be distinguished by color.",
    wcag: ["1.4.1", "1.4.3"],
    phase: 1,
  },
  {
    id: "focus_indicator",
    label: "Focus Visibility Check",
    description: "Tabs through every element and verifies each has a clearly visible focus ring.",
    wcag: ["2.4.7"],
    phase: 2,
  },
  {
    id: "form_errors",
    label: "Form Error Handling",
    description: "Submits forms with invalid data and checks that errors are descriptive, associated with fields, and provide correction hints.",
    wcag: ["3.3.1", "3.3.2", "3.3.3"],
    phase: 2,
  },
  {
    id: "page_structure",
    label: "Page Structure & Semantics",
    description: "Checks alt text, headings, page title, link text, lang attribute, touch targets, iframes, and ARIA misuse.",
    wcag: ["1.1.1", "1.3.1", "1.4.1", "2.4.2", "2.4.4", "2.5.5", "3.1.1", "4.1.2"],
    phase: 1,
  },
];

const PHASE_LABEL: Record<number, string> = {
  1: "Core Tests",
  2: "Extended Tests",
  3: "Phase 3",
};

interface Props {
  selected: string[];
  onChange: (selected: string[]) => void;
}

export default function TestSelector({ selected, onChange }: Props) {
  function toggle(id: string) {
    onChange(
      selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id]
    );
  }

  const phases = [...new Set(TEST_OPTIONS.map((t) => t.phase))].sort();

  return (
    <fieldset>
      <legend className="text-sm font-medium mb-3" style={{ color: "var(--text)" }}>
        Select Tests{" "}
        <span className="text-xs font-normal" style={{ color: "var(--muted)" }}>
          ({selected.length} selected)
        </span>
      </legend>
      <div className="space-y-5">
        {phases.map((phase) => (
          <div key={phase}>
            <p
              className="text-xs font-semibold uppercase tracking-widest mb-2"
              style={{ color: "var(--muted)" }}
            >
              {PHASE_LABEL[phase]}
            </p>
            <div className="space-y-2">
              {TEST_OPTIONS.filter((t) => t.phase === phase).map((test) => {
                const checked = selected.includes(test.id);
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
                      className="mt-0.5 h-4 w-4 rounded"
                      style={{ accentColor: "var(--lime)" }}
                    />
                    <div className="flex-1 min-w-0">
                      <p
                        className="text-sm font-medium"
                        style={{ color: checked ? "var(--lime)" : "var(--text)" }}
                      >
                        {test.label}
                      </p>
                      <p className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>
                        {test.description}
                      </p>
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {test.wcag.map((c) => (
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
          </div>
        ))}
      </div>
    </fieldset>
  );
}
