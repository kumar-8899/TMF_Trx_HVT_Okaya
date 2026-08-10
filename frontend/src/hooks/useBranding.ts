/** App identity from config (GET /branding, public). One fetch per session;
 * defaults render immediately so the shell never flashes empty. */
import { useEffect, useState } from "react";

export interface Branding {
  name: string; short: string; product: string; tagline: string; version?: string;
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
