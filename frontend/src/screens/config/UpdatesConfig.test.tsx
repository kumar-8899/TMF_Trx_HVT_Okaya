import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mockFetch } from "../../test/fetchMock";
import { UpdatesConfig } from "./UpdatesConfig";

describe("UpdatesConfig", () => {
  it("shows a distinct failure message when the check itself fails (not 'up to date')", async () => {
    mockFetch({
      "GET /update/offers": {
        body: { current: { version: "1.15.0", app_version: "1.0.0", abi: -1 }, offers: [], source: "owner/repo" },
      },
      "GET /update/status": { body: { backups: [], last_known_good: null } },
      "POST /update/check": {
        // The backend is network-tolerant: a failed check still returns 200 with `error` set and
        // `available: null` (core.services.updates.UpdateService.check), NOT an HTTP error.
        body: { checked_at: 0, current: { version: "1.15.0" }, available: null, error: "404 Not Found" },
      },
    });
    render(<UpdatesConfig />);
    const btn = () => screen.getByText("Check for application updates").closest("button")!;
    await waitFor(() => expect(btn()).not.toBeDisabled());   // waits for /update/offers (sets `source`)
    fireEvent.click(btn());
    await waitFor(() => expect(screen.getByText(/Update check failed: 404 Not Found/)).toBeInTheDocument());
    expect(screen.queryByText(/up to date/)).not.toBeInTheDocument();
  });

  it("shows the neutral message on a genuine successful check with no update", async () => {
    mockFetch({
      "GET /update/offers": {
        body: { current: { version: "1.15.0", app_version: "1.0.0", abi: -1 }, offers: [], source: "owner/repo" },
      },
      "GET /update/status": { body: { backups: [], last_known_good: null } },
      "POST /update/check": {
        body: { checked_at: 0, current: { version: "1.15.0" }, available: null },
      },
    });
    render(<UpdatesConfig />);
    const btn = () => screen.getByText("Check for application updates").closest("button")!;
    await waitFor(() => expect(btn()).not.toBeDisabled());
    fireEvent.click(btn());
    await waitFor(() => expect(screen.getByText(/up to date/)).toBeInTheDocument());
  });
});
