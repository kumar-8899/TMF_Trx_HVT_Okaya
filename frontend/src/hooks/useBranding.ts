/** App identity from config (GET /branding, public). One fetch per session;
 * defaults render immediately so the shell never flashes empty. */
import { useEffect, useState } from "react";

export interface Branding {
  name: string; short: string; product: string; tagline: string; version?: string;
}

export const DEFAULT_BRANDING: Branding = {
  name: "Test & Measurement", short: "T",
  product: "Test & Measurement Framework",
  tagline: "Authorised access only. All sessions are encrypted.",
};

let cache: Branding | null = null;

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
