import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PointCheck — WCAG 2.1 Accessibility Tester",
  description:
    "WCAG 2.1 Level AA accessibility testing powered by Allen AI's Molmo2 vision-language model. Catches failures that Axe and Lighthouse miss.",
  icons: {
    icon: "/logo.svg",
    shortcut: "/logo.svg",
    apple: "/logo.svg",
  },
  openGraph: {
    title: "PointCheck — WCAG 2.1 Accessibility Tester",
    description:
      "WCAG 2.1 Level AA accessibility testing powered by Allen AI's Molmo2 vision-language model. Catches failures that Axe and Lighthouse miss.",
    url: "https://pointcheck.org",
    type: "website",
    siteName: "PointCheck",
  },
  alternates: {
    canonical: "https://pointcheck.org",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full">
      <body
        className="min-h-full flex flex-col antialiased"
        style={{ background: "var(--bg)", color: "var(--text)" }}
      >
        {/* ── Header ── */}
        <header
          className="px-6 py-4 flex items-center justify-between"
          style={{ background: "var(--surface)", borderBottom: "1px solid var(--border)" }}
        >
          <a href="/" className="flex items-center gap-3 no-underline">
            <img
              src="/logo.svg"
              alt="PointCheck"
              className="w-10 h-10"
              style={{ display: "block" }}
            />
            <div>
              <span
                className="font-semibold leading-none tracking-tight block"
                style={{ color: "var(--text)" }}
              >
                PointCheck
              </span>
              <span className="text-xs mt-0.5 block" style={{ color: "var(--muted)" }}>
                WCAG 2.1 Level AA — Powered by OLMo2 &amp; Molmo2
              </span>
            </div>
          </a>
          <nav className="flex items-center gap-5 text-sm" style={{ color: "var(--muted)" }}>
            <a
              href="/about"
              className="transition-colors hover:text-current"
              style={{ color: "var(--muted)" }}
              onMouseEnter={(e) =>
                ((e.target as HTMLElement).style.color = "var(--text)")
              }
              onMouseLeave={(e) =>
                ((e.target as HTMLElement).style.color = "var(--muted)")
              }
            >
              About
            </a>
            <a
              href="https://github.com/BrendanWorks/wcag-molmoweb-tester"
              target="_blank"
              rel="noopener noreferrer"
              className="transition-colors"
              style={{ color: "var(--muted)" }}
              onMouseEnter={(e) =>
                ((e.target as HTMLElement).style.color = "var(--lime)")
              }
              onMouseLeave={(e) =>
                ((e.target as HTMLElement).style.color = "var(--muted)")
              }
            >
              GitHub
            </a>
          </nav>
        </header>

        {/* ── Page content ── */}
        <main className="flex-1 flex flex-col">{children}</main>

        {/* ── Footer ── */}
        <footer
          className="px-6 py-8 mt-auto"
          style={{ borderTop: "1px solid var(--border)", background: "var(--surface)" }}
        >
          <div className="max-w-4xl mx-auto flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 text-xs"
            style={{ color: "var(--muted)" }}>
            <div className="space-y-1">
              <p>© 2026 PointCheck. All rights reserved.</p>
              <p>
                Built with{" "}
                <a
                  href="https://allenai.org"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: "var(--lime)" }}
                >
                  Allen AI OLMo2 and Molmo2
                </a>
              </p>
            </div>
            <nav className="flex flex-wrap gap-x-5 gap-y-1">
              <a href="/about" style={{ color: "var(--muted)" }}
                className="transition-colors hover:text-white">About</a>
              <a href="/privacy" style={{ color: "var(--muted)" }}
                className="transition-colors hover:text-white">Privacy</a>
              <a href="/terms" style={{ color: "var(--muted)" }}
                className="transition-colors hover:text-white">Terms</a>
              <a
                href="https://github.com/BrendanWorks/wcag-molmoweb-tester"
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: "var(--muted)" }}
                className="transition-colors hover:text-white"
              >
                GitHub
              </a>
              <a
                href="mailto:brendanworks@gmail.com"
                style={{ color: "var(--muted)" }}
                className="transition-colors hover:text-white"
              >
                Contact
              </a>
            </nav>
          </div>
        </footer>
      </body>
    </html>
  );
}
