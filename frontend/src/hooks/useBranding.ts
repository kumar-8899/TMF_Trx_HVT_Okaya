/** App identity from config (GET /branding, public). One fetch per session;
 * defaults render immediately so the shell never flashes empty. */
import { useEffect, useState } from "react";

export interface Branding {
  name: string; short: string; product: string; tagline: string; version?: string;
  framework_version?: string;
  /** The application's OWN version (RELEASE.json / app/<slug>/VERSION); absent on a bare framework. */
  app_version?: string | null;
  logo_client?: string; logo_exeliq?: string;   // data: URLs (issue #7)
}

export const DEFAULT_BRANDING: Branding = {
  name: "Test & Measurement", short: "T",
  product: "Test & Measurement Framework",
  tagline: "Authorised access only. All sessions are encrypted.",
  logo_client: "", logo_exeliq: "",
};

let cache: Branding | null = null;

/** Drop the session cache so the next useBranding mount re-fetches (after an edit). */
export function resetBranding(): void {
  cache = null;
}

/** The version an operator means by "the app's version": the application's own when it has one,
 * else the framework's. Empty until /branding answers. */
export function displayVersion(b: Branding): string {
  return b.app_version || b.version || b.framework_version || "";
}

export function useBranding(): Branding {
  const [b, setB] = useState<Branding>(cache ?? DEFAULT_BRANDING);
  useEffect(() => {
    if (cache) return;
    fetch("/branding").then((r) => (r.ok ? r.json() : null)).then((j) => {
      if (j?.name) {
        const merged: Branding = { ...DEFAULT_BRANDING, ...j };
        cache = merged;
        setB(merged);
        document.title = merged.product;
      }
    }).catch(() => {});
  }, []);
  return b;
}
