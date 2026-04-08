import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms of Use — PointCheck",
  description: "PointCheck terms of use. Only test sites you own or have permission to test.",
};

export default function TermsPage() {
  return (
    <div className="flex-1 max-w-2xl mx-auto w-full px-6 py-14">
      <h2
        className="text-2xl font-bold tracking-tight mb-6"
        style={{ color: "var(--text)" }}
      >
        Terms of Use
      </h2>

      <div className="space-y-5 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        <p style={{ color: "var(--text)" }}>
          PointCheck is a free tool. Using it responsibly means following a few
          straightforward rules.
        </p>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
            Only test what you control
          </h3>
          <p>
            PointCheck fires a headless browser at whatever URL you submit. It
            navigates the page, runs JavaScript, and captures screenshots. Only
            submit URLs for websites you own or have been explicitly authorized to
            test. Submitting a URL you don&apos;t have permission to test may violate
            the target site&apos;s terms of service, applicable computer access laws,
            or both.
          </p>
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
            No warranty
          </h3>
          <p>
            PointCheck is provided as-is. Accessibility testing is inherently
            incomplete — automated tools catch a subset of real issues. A passing
            result is not a certification of WCAG compliance. Use the output as a
            starting point, not a finish line.
          </p>
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
            No abuse
          </h3>
          <p>
            Don&apos;t use PointCheck to test at high volume, to probe sites for
            security vulnerabilities, or for anything that would harm other
            people&apos;s infrastructure. The tool is designed for accessibility
            auditing, full stop.
          </p>
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
            Contact
          </h3>
          <p>
            Questions or concerns:{" "}
            <a href="mailto:brendanworks@gmail.com" style={{ color: "var(--lime)" }}>
              brendanworks@gmail.com
            </a>
          </p>
        </section>

        <p
          className="pt-4 text-xs"
          style={{ color: "var(--border)", borderTop: "1px solid var(--border)" }}
        >
          © 2026 Brendan Works. All rights reserved.
        </p>
      </div>
    </div>
  );
}
