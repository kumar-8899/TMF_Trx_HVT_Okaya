/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev server proxies API paths to the Python edge so the client uses relative URLs.
const API = "http://127.0.0.1:8000";
const proxied = ["/auth", "/modules", "/healthz", "/readyz", "/logs", "/recipes",
  "/instruments", "/runs", "/variables", "/diagnostics"];

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      ...Object.fromEntries(proxied.map((p) => [p, API])),
      "/ws": { target: API, ws: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
  },
});
