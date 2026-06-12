import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AuthProvider } from "../auth/AuthContext";
import { mockFetch } from "../test/fetchMock";
import { Reports } from "./Reports";

describe("Reports", () => {
  it("renders analytics + run list", async () => {
    mockFetch({
      "GET /reports/analytics": {
        body: {
          total: 2, passed: 1, failed: 1, yield: 50.0,
          by_recipe: { inv: { total: 2, passed: 1, failed: 1 } },
          by_result: { PASS: 1, FAIL: 1 },
        },
      },
      "GET /reports": {
        body: {
          items: [{ run_id: "R1", recipe_id: "inv", result: "PASS", finished_ts: 1700000000, steps: [] }],
          next_cursor: null, total: 1,
        },
      },
    });
    render(<MemoryRouter><AuthProvider><Reports /></AuthProvider></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("R1")).toBeInTheDocument());
    expect(screen.getByText("50")).toBeInTheDocument(); // yield
    expect(screen.getByText("By recipe")).toBeInTheDocument();
  });
});
