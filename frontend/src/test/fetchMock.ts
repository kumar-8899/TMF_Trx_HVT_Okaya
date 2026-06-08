import { vi } from "vitest";

type Route = { status?: number; body?: unknown };

// Mock global.fetch: map "METHOD path" -> {status, body}. Unmapped -> 404.
export function mockFetch(routes: Record<string, Route>) {
  globalThis.fetch = vi.fn(async (url: any, opts: any = {}) => {
    const method = (opts.method || "GET").toUpperCase();
    const path = String(url);
    const key = `${method} ${path}`;
    const route = routes[key] ?? routes[path];
    const status = route?.status ?? (route ? 200 : 404);
    const body = route?.body ?? null;
    return {
      ok: status >= 200 && status < 300,
      status,
      text: async () => (body === null ? "" : JSON.stringify(body)),
    } as Response;
  }) as any;
  return globalThis.fetch as any;
}
