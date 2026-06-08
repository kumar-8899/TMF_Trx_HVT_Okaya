import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mockFetch } from "../test/fetchMock";
import { Dashboard } from "./Dashboard";

describe("Dashboard", () => {
  it("renders modules from /modules/status and the ready chip", async () => {
    mockFetch({
      "GET /modules/status": {
        body: {
          loaded: ["auth"], skipped: [],
          modules: [{ id: "auth", status: "loaded", reason: "", display_name: "User Authentication" }],
        },
      },
      "GET /readyz": { body: { ready: true, checks: {} } },
    });
    render(<Dashboard />);
    await waitFor(() => expect(screen.getByText("User Authentication")).toBeInTheDocument());
    expect(screen.getByText("ready")).toBeInTheDocument();
  });
});
