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
    description: "Checks alt text on images, heading hierarchy, page title, vague link text, lang attribute, and ARIA misuse.",
    wcag: ["1.1.1", "1.3.1", "2.4.2", "2.4.4", "3.1.1", "4.1.2"],
    phase: 1,
  },
];

const PHASE_LABEL: Record<number, string> = {
  1: "Phase 1 — MVP",
  2: "Phase 2",
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
      <legend className="text-sm font-medium text-slate-700 mb-3">
        Select Tests <span className="text-slate-400 font-normal">({selected.length} selected)</span>
      </legend>
      <div className="space-y-5">
        {phases.map((phase) => (
          <div key={phase}>
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">
              {PHASE_LABEL[phase]}
            </p>
            <div className="space-y-2">
              {TEST_OPTIONS.filter((t) => t.phase === phase).map((test) => {
                const checked = selected.includes(test.id);
                return (
                  <label
                    key={test.id}
                    className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors
                      ${checked
                        ? "border-blue-300 bg-blue-50"
                        : "border-slate-200 bg-white hover:border-slate-300"
                      }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggle(test.id)}
                      className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600
                                 focus:ring-2 focus:ring-blue-500"
                    />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-800">{test.label}</p>
                      <p className="text-xs text-slate-500 mt-0.5">{test.description}</p>
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {test.wcag.map((c) => (
                          <span
                            key={c}
                            className="inline-block text-xs bg-slate-100 text-slate-600
                                       rounded px-1.5 py-0.5 font-mono"
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
