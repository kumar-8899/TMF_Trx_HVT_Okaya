import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../auth/AuthContext";
import { MesAlertDialog } from "./MesAlertDialog";

type Handler = (method: string, path: string) => { status?: number; body?: unknown } | undefined;

function routeFetch(handler: Handler) {
  const f = vi.fn(async (url: any, opts: any = {}) => {
    const method = (opts.method || "GET").toUpperCase();
    const r = handler(method, String(url).split("?")[0]);
    const status = r?.status ?? (r ? 200 : 404);
    return { ok: status >= 200 && status < 300, status, text: async () => (r?.body == null ? "" : JSON.stringify(r.body)) } as Response;
  });
  globalThis.fetch = f as any;
  return f;
}

const FAIL = { run_id: "R1", serial: "SN-1", result: "PASS", status: "failed", error: "MES database timed out", ts: 1760000000 };

function mount(perms: string[] = ["TEST.RUN"]) {
  localStorage.setItem("tmf.token", "tok");
  return {
    perms,
    ui: <MemoryRouter><AuthProvider><MesAlertDialog /></AuthProvider></MemoryRouter>,
  };
}

beforeEach(() => { localStorage.clear(); });
afterEach(() => { localStorage.clear(); });

describe("MesAlertDialog", () => {
  it("prompts with the serial and error, and Retry clears it once delivery works", async () => {
    let alerts = [FAIL];
    let retryOk = false;
    const f = routeFetch((m, p) => {
      if (p === "/auth/me") return { body: { username: "op", role: "operator", permissions: ["TEST.RUN"] } };
      if (m === "GET" && p === "/mes/alerts") return { body: { items: alerts, count: alerts.length } };
      if (m === "POST" && p === "/mes/alerts/R1/retry") {
        if (retryOk) { alerts = []; return { body: { ok: true, detail: "delivered" } }; }
        return { body: { ok: false, detail: "still unreachable" } };
      }
    });
    render(mount().ui);
    expect(await screen.findByText(/was NOT sent to MES/)).toBeInTheDocument();
    expect(screen.getByText(/SN-1/)).toBeInTheDocument();
    expect(screen.getByText("MES database timed out")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("still unreachable")).toBeInTheDocument();     // stays loud
    expect(screen.getByText(/was NOT sent to MES/)).toBeInTheDocument();

    retryOk = true;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.queryByText(/was NOT sent to MES/)).not.toBeInTheDocument());
    expect(f.mock.calls.filter(([u, o]: any) => String(u) === "/mes/alerts/R1/retry" && o?.method === "POST")).toHaveLength(2);
  });

  it("Dismiss asks for confirmation, then calls the audited dismiss endpoint", async () => {
    let alerts = [FAIL];
    const f = routeFetch((m, p) => {
      if (p === "/auth/me") return { body: { username: "op", role: "operator", permissions: ["TEST.RUN"] } };
      if (m === "GET" && p === "/mes/alerts") return { body: { items: alerts, count: alerts.length } };
      if (m === "POST" && p === "/mes/alerts/R1/dismiss") { alerts = []; return { body: { ok: true } }; }
    });
    render(mount().ui);
    fireEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
    expect(await screen.findByText("Dismiss without delivering?")).toBeInTheDocument();
    expect(f.mock.calls.some(([u]: any) => String(u).endsWith("/dismiss"))).toBe(false);   // not yet
    const dismissButtons = screen.getAllByRole("button", { name: "Dismiss" });
    fireEvent.click(dismissButtons[dismissButtons.length - 1]);                       // the confirm dialog's
    await waitFor(() => expect(f.mock.calls.some(([u]: any) => String(u) === "/mes/alerts/R1/dismiss")).toBe(true));
    await waitFor(() => expect(screen.queryByText(/was NOT sent to MES/)).not.toBeInTheDocument());
  });

  it("'Remind me later' hides it until a NEW failure appears", async () => {
    let alerts: any[] = [FAIL];
    routeFetch((m, p) => {
      if (p === "/auth/me") return { body: { username: "op", role: "operator", permissions: ["TEST.RUN"] } };
      if (m === "GET" && p === "/mes/alerts") return { body: { items: alerts, count: alerts.length } };
    });
    render(mount().ui);
    fireEvent.click(await screen.findByRole("button", { name: "Remind me later" }));
    await waitFor(() => expect(screen.queryByText(/was NOT sent to MES/)).not.toBeInTheDocument());
    alerts = [FAIL, { ...FAIL, run_id: "R2", serial: "SN-2" }];
    window.dispatchEvent(new Event("tmf:mes-refresh"));
    expect(await screen.findByText(/2 test results were NOT sent to MES/)).toBeInTheDocument();
  });

  it("does nothing for a user without TEST.RUN (no polling, no dialog)", async () => {
    const f = routeFetch((_m, p) => {
      if (p === "/auth/me") return { body: { username: "v", role: "viewer", permissions: ["REPORT.VIEW"] } };
    });
    render(mount(["REPORT.VIEW"]).ui);
    await waitFor(() => expect(f).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 50));
    expect(f.mock.calls.some(([u]: any) => String(u).startsWith("/mes/alerts"))).toBe(false);
    expect(screen.queryByText(/NOT sent to MES/)).not.toBeInTheDocument();
  });

  it("stays silent when the MES module isn't loaded (404)", async () => {
    routeFetch((_m, p) => {
      if (p === "/auth/me") return { body: { username: "op", role: "operator", permissions: ["TEST.RUN"] } };
      return undefined;                          // /mes/alerts -> 404
    });
    render(mount().ui);
    await new Promise((r) => setTimeout(r, 100));
    expect(screen.queryByText(/NOT sent to MES/)).not.toBeInTheDocument();
  });
});
