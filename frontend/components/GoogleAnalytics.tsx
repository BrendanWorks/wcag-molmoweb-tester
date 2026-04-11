"use client";

/**
 * Sends a GA4 page_view event on every client-side route change.
 *
 * Next.js App Router does SPA navigation — the gtag('config', ...) call in
 * layout.tsx only fires once on initial load.  Without this component, GA4
 * never sees /about, /privacy, or /terms as separate page views.
 *
 * Usage: render <GoogleAnalytics measurementId="G-XXXXXXXX" /> once inside
 * the root layout (already done in layout.tsx).
 */

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect } from "react";

type GtagFn = (command: string, ...args: unknown[]) => void;

interface Props {
  measurementId: string;
}

export default function GoogleAnalytics({ measurementId }: Props) {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    const gtag = (window as unknown as { gtag?: GtagFn }).gtag;
    if (typeof gtag !== "function") return;

    const url = pathname + (searchParams.toString() ? `?${searchParams}` : "");
    gtag("config", measurementId, { page_path: url });
  }, [pathname, searchParams, measurementId]);

  return null;
}
