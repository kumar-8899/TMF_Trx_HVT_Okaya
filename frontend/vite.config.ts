/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev server proxies API calls to the Python edge. Instead of an allow-list of
// prefixes (which kept going stale as modules landed), proxy everything to the
// backend EXCEPT Vite's own assets/source and real browser navigations (SPA
// routes). `bypass` returning a path makes Vite serve it; returning undefined
// proxies it. WS-bearing prefixes are listed explicitly so Vite's HMR socket is
// never hijacked.
const API = "http://127.0.0.1:8000";

function serveSpa(req: { url?: string; headers: Record<string, any> }): string | undefined {
  const url = (req.url || "").split("?")[0];
  if (url.startsWith("/@") || url.startsWith("/src/") || url.startsWith("/node_modules/")) return req.url; // Vite internals/source
  if (/\.[a-zA-Z0-9]+$/.test(url)) return req.url;                       // an asset file (.js/.css/.svg/…)
  if (String(req.headers.accept || "").includes("text/html")) return req.url; // SPA navigation → index.html
  return undefined;                                                      // → proxy to the backend (REST)
}

const api = (ws = false) => ({ target: API, ws, bypass: serveSpa });

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // WS-bearing endpoints (explicit so HMR's socket is untouched)
      "/ws": api(true),
      "/instruments": api(true),
      "/diagnostics": api(true),
      "/health": api(true),
      // everything else that isn't a Vite asset/source or an SPA navigation
      "^/(?!@|src/|node_modules/).+": api(false),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
  },
});
