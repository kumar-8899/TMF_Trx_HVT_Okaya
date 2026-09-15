import { describe, expect, it, vi } from "vitest";

import { buildRegistry } from "./registry";

function Comp() {
  return null;
}

describe("buildRegistry (app screen-override + page registry, TEMPLATE.md §1.3)", () => {
  it("registers a default-exported screen override by key", () => {
    const { screens } = buildRegistry({
      "./overrides/runs.tsx": { default: { key: "runs", component: Comp } },
    });
    expect(screens.runs).toBe(Comp);
  });

  it("registers a valid app page (path under /app/)", () => {
    const { pages } = buildRegistry({
      "./overrides/pages.tsx": {
        pages: [{ path: "/app/gauges", navLabel: "Gauges", permission: "TEST.RUN", component: Comp }],
      },
    });
    expect(pages).toEqual([
      { path: "/app/gauges", navLabel: "Gauges", permission: "TEST.RUN", component: Comp },
    ]);
  });

  it("merges pages contributed across multiple override modules", () => {
    const { pages } = buildRegistry({
      "./overrides/a.tsx": { pages: [{ path: "/app/a", navLabel: "A", component: Comp }] },
      "./overrides/b.tsx": { pages: [{ path: "/app/b", navLabel: "B", component: Comp }] },
    });
    expect(pages.map((p) => p.path).sort()).toEqual(["/app/a", "/app/b"]);
  });

  it("a page can coexist with a default screen override in the same module", () => {
    const { screens, pages } = buildRegistry({
      "./overrides/combo.tsx": {
        default: { key: "runs", component: Comp },
        pages: [{ path: "/app/dashboard", navLabel: "Dashboard", component: Comp }],
      },
    });
    expect(screens.runs).toBe(Comp);
    expect(pages).toHaveLength(1);
  });

  it("rejects a page whose path does not start with /app/, and warns", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { pages } = buildRegistry({
      "./overrides/bad.tsx": {
        pages: [{ path: "/gauges", navLabel: "Gauges", component: Comp }],
      },
    });
    expect(pages).toEqual([]);
    expect(warn).toHaveBeenCalledOnce();
    warn.mockRestore();
  });

  it.each([
    [{ path: "/app/x", navLabel: "", component: Comp }],   // missing navLabel
    [{ path: "/app/x", navLabel: "X" }],                    // missing component
    [{ navLabel: "X", component: Comp }],                   // missing path
  ] as any[])("rejects an incomplete page entry %j", (bad) => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { pages } = buildRegistry({ "./overrides/bad.tsx": { pages: [bad] } });
    expect(pages).toEqual([]);
    warn.mockRestore();
  });

  it("empty overrides directory -> no screens, no pages (framework defaults)", () => {
    const { screens, pages } = buildRegistry({});
    expect(screens).toEqual({});
    expect(pages).toEqual([]);
  });
});
