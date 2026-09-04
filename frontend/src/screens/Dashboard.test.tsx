import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AuthProvider } from "../auth/AuthContext";
import { mockFetch } from "../test/fetchMock";
import { ColorModeProvider } from "../theme/ColorMode";
import { Dashboard } from "./Dashboard";

// Dashboard reads theme.palette.status (our augmented palette) directly, so it needs the
// real ThemeProvider — not just MUI's default theme — same as in production (main.tsx).
function Providers({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter>
      <ColorModeProvider>
        <AuthProvider>{children}</AuthProvider>
      </ColorModeProvider>
    </MemoryRouter>
  );
}

describe("Dashboard", () => {
  it("shows the all-clear banner when nothing needs attention", async () => {
    mockFetch({
      "GET /modules/status": {
        body: { loaded: ["auth"], skipped: [], modules: [{ id: "auth", status: "loaded", reason: "", display_name: "User Authentication" }] },
      },
      "GET /readyz": { body: { ready: true, checks: {}, stations: { st1: "online" } } },
      "GET /healthz": { body: { status: "ok", version: "1.14.0" } },
      "GET /variables/instances": { body: [{ id: "psu-1", library: "keysight_e36xx", state: "connected", simulated: false }] },
      "GET /reports/analytics/dashboard": {
        body: {
          configured: true,
          kpis: { runs: 12, passed: 10, failed: 2, yield: 83.3, units: 9, fpy: 90.0, avg_cycle_s: 4.2 },
          passfail_daily: [{ date: "2026-09-01", pass: 5, fail: 1 }, { date: "2026-09-02", pass: 5, fail: 1 }],
        },
      },
    });
    render(<Providers><Dashboard /></Providers>);
    await waitFor(() => expect(screen.getByText("All systems normal")).toBeInTheDocument());
    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();        // runs (7d) tile
    expect(screen.getByText("psu-1")).toBeInTheDocument();     // instrument row
  });

  it("surfaces a disconnected instrument as an attention card", async () => {
    mockFetch({
      "GET /modules/status": { body: { loaded: [], skipped: ["mes"], modules: [{ id: "mes", status: "skipped", reason: "no license", display_name: "MES" }] } },
      "GET /readyz": { body: { ready: true, checks: {}, stations: { st1: "online" } } },
      "GET /healthz": { body: { status: "ok", version: "1.14.0" } },
      "GET /variables/instances": { body: [{ id: "psu-1", library: "keysight_e36xx", state: "disconnected", simulated: false }] },
      "GET /reports/analytics/dashboard": {
        body: { configured: false, kpis: {}, passfail_daily: [] },
      },
    });
    render(<Providers><Dashboard /></Providers>);
    await waitFor(() => expect(screen.getByText("1 instrument not connected")).toBeInTheDocument());
    expect(screen.getByText("Report database not configured")).toBeInTheDocument();
    expect(screen.getByText(/module.*not active/)).toBeInTheDocument();
  });
});
