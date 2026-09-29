import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../../test/fetchMock";
import { UpdatesConfig } from "./UpdatesConfig";

afterEach(() => { vi.useRealTimers(); });

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

  it("air_gapped: Scan for updates stages what it finds and shows a summary", async () => {
    mockFetch({
      "GET /update/offers": {
        body: { current: { version: "1.16.0" }, offers: [], source: null, station_mode: "air_gapped" },
      },
      "GET /update/status": { body: { backups: [], last_known_good: null } },
      "POST /update/scan-incoming": {
        body: { found: [
          { track: "app", version: "2.0.0", scope: "full" },
          { track: "app", version: "2.0.1", scope: "app-payload" },
        ] },
      },
    });
    render(<UpdatesConfig />);
    const btn = await screen.findByText("Scan for updates on this PC");
    fireEvent.click(btn.closest("button")!);
    await waitFor(() => expect(screen.getByText(
      /Staged from local files: app 2\.0\.0 \(full\), app 2\.0\.1 \(app-payload\)/)).toBeInTheDocument());
  });

  it("air_gapped: Scan for updates reports nothing found without erroring", async () => {
    mockFetch({
      "GET /update/offers": {
        body: { current: { version: "1.16.0" }, offers: [], source: null, station_mode: "air_gapped" },
      },
      "GET /update/status": { body: { backups: [], last_known_good: null } },
      "POST /update/scan-incoming": { body: { found: [] } },
    });
    render(<UpdatesConfig />);
    const btn = await screen.findByText("Scan for updates on this PC");
    fireEvent.click(btn.closest("button")!);
    await waitFor(() => expect(screen.getByText(/No update files found/)).toBeInTheDocument());
  });

  it("air_gapped: Scan for updates surfaces a per-slot error without hiding a good slot", async () => {
    mockFetch({
      "GET /update/offers": {
        body: { current: { version: "1.16.0" }, offers: [], source: null, station_mode: "air_gapped" },
      },
      "GET /update/status": { body: { backups: [], last_known_good: null } },
      "POST /update/scan-incoming": {
        body: { found: [
          { track: "app", version: "2.0.0", scope: "full" },
          { slot: "app-payload", error: "artifact hash mismatch: got deadbe… want abc123…" },
        ] },
      },
    });
    render(<UpdatesConfig />);
    const btn = await screen.findByText("Scan for updates on this PC");
    fireEvent.click(btn.closest("button")!);
    await waitFor(() => expect(screen.getByText(/Staged from local files: app 2\.0\.0 \(full\)/)).toBeInTheDocument());
    expect(screen.getByText(/app-payload: artifact hash mismatch/)).toBeInTheDocument();
  });

  it("relaunch waits for the backend to return, then re-fetches (not a static message)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let offersCalls = 0;
    globalThis.fetch = vi.fn(async (url: any, opts: any = {}) => {
      const method = (opts.method || "GET").toUpperCase();
      const path = String(url).split("?")[0];
      let body: any = null;
      if (path === "/update/offers") {
        offersCalls += 1;
        body = { current: { version: "1.0.3" }, source: "o/r",
          offers: [{ release_id: "x1", track: "app", version: "1.0.4", verified: true,
            verdict: { applicable: true }, status: "apply_pending" }] };
      } else if (path === "/update/status") body = { backups: [], last_known_good: null };
      else if (path === "/update/relaunch/x1" && method === "POST") body = { ok: true };
      else if (path === "/healthz") body = { status: "ok", version: "1.0.4" };
      return { ok: true, status: 200, text: async () => JSON.stringify(body) } as Response;
    }) as any;

    render(<UpdatesConfig />);
    const relaunchBtn = await screen.findByRole("button", { name: "Relaunch" });
    expect(offersCalls).toBe(1);
    fireEvent.click(relaunchBtn);

    await screen.findByText(/waiting for it to come back/);        // real "reconnecting" state
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });   // past the 3s settle + first poll
    await waitFor(() => expect(screen.queryByText(/waiting for it to come back/)).not.toBeInTheDocument());
    expect(offersCalls).toBeGreaterThan(1);                        // refresh() re-ran after /healthz came back
    expect(screen.getByText(/Station is back up/)).toBeInTheDocument();
  });
});
