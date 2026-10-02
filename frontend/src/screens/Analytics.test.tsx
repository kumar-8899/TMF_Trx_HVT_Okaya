import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AuthProvider } from "../auth/AuthContext";
import { mockFetch } from "../test/fetchMock";
import { ColorModeProvider } from "../theme/ColorMode";
import { Analytics } from "./Analytics";

// Analytics reads theme.palette.status, so it needs the real ThemeProvider (as in production).
function Providers({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter>
      <ColorModeProvider>
        <AuthProvider>{children}</AuthProvider>
      </ColorModeProvider>
    </MemoryRouter>
  );
}

// What the backend returns when no report DB is configured (store.py: dashboard() early return):
// "kpis" is an EMPTY object, every list is empty.
const UNCONFIGURED = {
  configured: false, kpis: {}, passfail_daily: [], by_model: [], by_shift: [], by_station: [],
  failure_pareto: [], param_pareto: [], fpy: { series: [], pbar: 0 },
  cycle: { histogram: [], imr: { points: [] } },
  models: [], operators: [], shifts: [], stations: [], detail_truncated: false,
};

describe("Analytics", () => {
  it("shows a dash, never 'undefined', for KPIs when no report DB is configured", async () => {
    mockFetch({ "GET /reports/analytics/dashboard": { body: UNCONFIGURED } });
    const { container } = render(<Providers><Analytics /></Providers>);
    await waitFor(() => expect(screen.getByText(/Report database not configured/)).toBeInTheDocument());
    expect(container.textContent).not.toContain("undefined");
    expect(container.textContent).not.toContain("NaN");
    // six KPI tiles, all empty
    expect(screen.getAllByText("—")).toHaveLength(6);
  });

  it("still formats real KPI values", async () => {
    mockFetch({
      "GET /reports/analytics/dashboard": {
        body: {
          ...UNCONFIGURED, configured: true,
          kpis: { runs: 12, passed: 10, failed: 2, aborted: 0, yield: 83.3, units: 9, fpy: 90.0, retest_rate: 5.5, avg_cycle_s: 4.2, median_cycle_s: 4.0 },
        },
      },
    });
    render(<Providers><Analytics /></Providers>);
    await waitFor(() => expect(screen.getByText("90%")).toBeInTheDocument());
    expect(screen.getByText("83.3%")).toBeInTheDocument();
    expect(screen.getByText("5.5%")).toBeInTheDocument();
    expect(screen.getByText("4.2s")).toBeInTheDocument();
  });
});
