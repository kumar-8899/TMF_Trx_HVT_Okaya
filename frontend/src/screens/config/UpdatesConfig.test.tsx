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

  it("online (default): shows Check, hides the Install-from-file inputs", async () => {
    mockFetch({
      "GET /update/offers": {
        body: { current: { version: "1.16.0" }, offers: [], source: "owner/repo" },   // no station_mode → online
      },
      "GET /update/status": { body: { backups: [], last_known_good: null } },
    });
    render(<UpdatesConfig />);
    await waitFor(() => expect(screen.getByText("Check for application updates")).toBeInTheDocument());
    expect(screen.queryByLabelText(".ksupdate path")).not.toBeInTheDocument();
    expect(screen.getByText(/install-from-file is disabled/)).toBeInTheDocument();
  });

  it("air_gapped: hides Check, shows the Install-from-file inputs", async () => {
    mockFetch({
      "GET /update/offers": {
        body: { current: { version: "1.16.0" }, offers: [], source: "owner/repo", station_mode: "air_gapped" },
      },
      "GET /update/status": { body: { backups: [], last_known_good: null } },
    });
    render(<UpdatesConfig />);
    await waitFor(() => expect(screen.getByLabelText(".ksupdate path")).toBeInTheDocument());
    expect(screen.queryByText("Check for application updates")).not.toBeInTheDocument();
    expect(screen.getByText(/Online check .* download is disabled/)).toBeInTheDocument();
  });
});
