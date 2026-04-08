import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "About — PointCheck",
  description:
    "PointCheck is a WCAG 2.1 Level AA accessibility tester built by Brendan Works, powered by Allen AI's Molmo2 vision-language model.",
};

export default function AboutPage() {
  return (
    <div className="flex-1 max-w-2xl mx-auto w-full px-6 py-14">
      <h2
        className="text-2xl font-bold tracking-tight mb-6"
        style={{ color: "var(--text)" }}
      >
        About PointCheck
      </h2>

      <div className="space-y-5 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        <p style={{ color: "var(--text)" }}>
          PointCheck is a WCAG 2.1 Level AA accessibility tester built by{" "}
          <a
            href="mailto:brendanworks@gmail.com"
            style={{ color: "var(--lime)" }}
          >
            Brendan Works
          </a>
          .
        </p>

        <p>
          Most automated accessibility tools — Axe, Lighthouse, browser
          extensions — work by inspecting the DOM. They can tell you if an
          image is missing alt text or if a button lacks an accessible name.
          What they can&apos;t do is look at the page the way a human eye would.
        </p>

        <p>
          PointCheck uses Allen AI&apos;s{" "}
          <a
            href="https://allenai.org"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "var(--lime)" }}
          >
            Molmo2
          </a>{" "}
          vision-language model to visually confirm whether focus indicators are
          actually visible — the kind of check that requires seeing the rendered
          page, not parsing its markup. This catches real failures that
          DOM-inspection tools miss entirely.
        </p>

        <p>
          The rest of the test suite covers keyboard navigation, 200% zoom
          reflow, color-blindness simulation, form error handling, and a broad
          page structure check. Results are narrated in plain English by Allen
          AI&apos;s OLMo2 language model.
        </p>

        <p>
          Paste any public URL, select your tests, and get a detailed
          accessibility report in seconds.
        </p>

        <p>
          Read the full technical writeup{" "}
          <span style={{ color: "var(--border)" }}>
            (Substack article — coming soon)
          </span>
          .
        </p>

        <div
          className="mt-8 pt-6 flex flex-wrap gap-4 text-xs"
          style={{ borderTop: "1px solid var(--border)" }}
        >
          <a
            href="https://github.com/BrendanWorks/wcag-molmoweb-tester"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "var(--lime)" }}
          >
            View source on GitHub →
          </a>
          <a href="mailto:brendanworks@gmail.com" style={{ color: "var(--muted)" }}>
            brendanworks@gmail.com
          </a>
        </div>
      </div>
    </div>
  );
}
