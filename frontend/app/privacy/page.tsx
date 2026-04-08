import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy — PointCheck",
  description: "PointCheck privacy policy. No tracking, no accounts, no stored data.",
};

export default function PrivacyPage() {
  return (
    <div className="flex-1 max-w-2xl mx-auto w-full px-6 py-14">
      <h2
        className="text-2xl font-bold tracking-tight mb-6"
        style={{ color: "var(--text)" }}
      >
        Privacy Policy
      </h2>

      <div className="space-y-5 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        <p style={{ color: "var(--text)" }}>
          Short version: PointCheck doesn&apos;t collect anything about you.
        </p>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
            URLs and test data
          </h3>
          <p>
            When you submit a URL for testing, it&apos;s sent to a backend service
            that runs the accessibility checks. Once the results are returned to
            your browser, the URL and all test data are discarded. Nothing is
            stored in a database. Nothing is logged to persistent storage.
          </p>
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
            No accounts
          </h3>
          <p>
            There are no user accounts, no login, no sign-up, and no email
            collection. You don&apos;t need to identify yourself to use PointCheck.
          </p>
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
            Analytics
          </h3>
          <p>
            PointCheck uses Google Analytics (GA4) to collect basic, anonymous
            usage data — page views and session counts. No personally identifiable
            information is collected. No user behaviour inside a test run is
            tracked. You can opt out using any standard browser extension that
            blocks Google Analytics.
          </p>
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
            Third-party infrastructure
          </h3>
          <p>
            The frontend is hosted on Vercel. The backend runs on Modal. Standard
            server logs (IP address, timestamp, HTTP method) may be retained by
            those platforms according to their own privacy policies. PointCheck
            does not control those logs.
          </p>
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
            Questions
          </h3>
          <p>
            Email{" "}
            <a href="mailto:brendanworks@gmail.com" style={{ color: "var(--lime)" }}>
              brendanworks@gmail.com
            </a>
            .
          </p>
        </section>
      </div>
    </div>
  );
}
