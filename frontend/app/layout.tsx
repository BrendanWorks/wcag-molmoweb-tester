import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";
import { WcagVersionProvider } from "@/components/WcagVersionProvider";
import HeaderVersion from "@/components/HeaderVersion";

export const metadata: Metadata = {
  title: "PointCheck — WCAG 2.1 & 2.2 Accessibility Tester",
  description:
    "WCAG 2.1 & 2.2 Level AA accessibility testing powered by Allen AI's Molmo2 vision-language model. Catches failures that Axe and Lighthouse miss.",
  icons: {
    icon: "/logo.svg",
    shortcut: "/logo.svg",
    apple: "/logo.svg",
  },
  openGraph: {
    title: "PointCheck — WCAG 2.1 & 2.2 Accessibility Tester",
    description:
      "WCAG 2.1 & 2.2 Level AA accessibility testing powered by Allen AI's Molmo2 vision-language model. Catches failures that Axe and Lighthouse miss.",
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
        <WcagVersionProvider>
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
              <HeaderVersion />
            </div>
          </a>
          <nav className="flex items-center gap-5 text-sm">
            <a href="/about" className="nav-link-muted">About</a>
            <a
              href="https://github.com/BrendanWorks/PointCheck"
              target="_blank"
              rel="noopener noreferrer"
              className="nav-link-lime"
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
                  Allen AI OLMo3 and Molmo2
                </a>
              </p>
              <p style={{ opacity: 0.75 }}>
                Free while in beta &middot; Built in Seattle &middot; Not a replacement for manual audits
              </p>
            </div>
            <nav className="flex flex-wrap gap-x-5 gap-y-1">
              <a href="/about" className="footer-link">About</a>
              <a href="/privacy" className="footer-link">Privacy</a>
              <a href="/terms" className="footer-link">Terms</a>
              <a
                href="https://github.com/BrendanWorks/PointCheck"
                target="_blank"
                rel="noopener noreferrer"
                className="footer-link"
              >
                GitHub
              </a>
              <a
                href="mailto:brendanworks@gmail.com"
                className="footer-link"
              >
                Contact
              </a>
            </nav>
          </div>
        </footer>
        </WcagVersionProvider>
        <Script
          src="https://www.googletagmanager.com/gtag/js?id=G-W08D0QMLTJ"
          strategy="afterInteractive"
        />
        <Script id="ga4-init" strategy="afterInteractive">{`
          window.dataLayer = window.dataLayer || [];
          function gtag(){dataLayer.push(arguments);}
          gtag('js', new Date());
          gtag('config', 'G-W08D0QMLTJ');
        `}</Script>
      </body>
    </html>
  );
}
