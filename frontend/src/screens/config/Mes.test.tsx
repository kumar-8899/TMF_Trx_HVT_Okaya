import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConfigMes } from "./Mes";

type Resp = { status?: number; body?: unknown } | undefined;
type Handler = (method: string, path: string, body: any) => Resp;

function routeFetch(handler: Handler) {
  const f = vi.fn(async (url: any, opts: any = {}) => {
    const method = (opts.method || "GET").toUpperCase();
    const body = opts.body ? JSON.parse(opts.body) : undefined;
    const r = handler(method, String(url).split("?")[0], body);
    const status = r?.status ?? (r ? 200 : 404);
    return { ok: status >= 200 && status < 300, status, text: async () => (r?.body == null ? "" : JSON.stringify(r.body)) } as Response;
  });
  globalThis.fetch = f as any;
  return f;
}

const FIELDS = [
  { name: "run_id", required: true, type: "STRING(64)" },
  { name: "serial_no", required: true, type: "STRING(128)" },
  { name: "result", required: true, type: "STRING(32)" },
  { name: "model", required: false, type: "STRING(128)" },
];
const STATUS = {
  stage: "st1", provider: "database", gate_enabled: true, publish_enabled: true, on_missing: "block",
  on_error: "block", provider_detail: { kind: "database" }, failed_pushes: 0,
};
const CONN = { provider: "mysql", host: "mes-db", port: 3306, user: "u", has_password: true };

function base(extra: Partial<Record<string, Resp | ((b: any) => Resp)>> = {}): Handler {
  return (m, p, b) => {
    const k = `${m} ${p}`;
    if (k in extra) { const v = extra[k]; return typeof v === "function" ? v(b) : v; }
    if (k === "GET /mes/status") return { body: STATUS };
    if (k === "GET /mes/db-config") return { body: { inbound: { connection: CONN }, outbound: {}, fields: FIELDS } };
    if (k === "PUT /mes/db-config") return { body: { inbound: b.inbound ?? { connection: CONN }, outbound: b.outbound ?? {}, fields: FIELDS } };
    if (k === "POST /mes/db/databases") return { body: { ok: true, items: ["mesdb", "plant"], detail: "" } };
    return undefined;
  };
}

afterEach(() => vi.restoreAllMocks());

describe("ConfigMes", () => {
  it("says WHY it can't be configured: missing permission vs module not loaded", async () => {
    routeFetch((_m, p) => (p === "/mes/status" ? { status: 403, body: { detail: "requires permission(s): SYSTEM.SETTINGS" } } : undefined));
    const { unmount } = render(<ConfigMes />);
    expect(await screen.findByText(/need the “Station settings” permission/)).toBeInTheDocument();
    unmount();
    routeFetch(() => undefined);                                         // 404 everywhere
    render(<ConfigMes />);
    expect(await screen.findByText(/MES module is not enabled/)).toBeInTheDocument();
  });

  it("switching transport persists the provider", async () => {
    const f = routeFetch(base({
      "GET /mes/status": { body: { ...STATUS, provider: "folder", provider_detail: { upstream_dir: "up", downstream_dir: "down" } } },
      "PUT /mes/config": (b) => ({ body: { ...STATUS, provider: b.provider } }),
    }));
    render(<ConfigMes />);
    fireEvent.click(await screen.findByRole("button", { name: "Database" }));
    await waitFor(() => expect(screen.getByText("Inbound — gate")).toBeInTheDocument());
    const put = f.mock.calls.find(([u, o]: any) => String(u) === "/mes/config" && o?.method === "PUT")!;
    expect(JSON.parse((put[1] as any).body)).toEqual({ provider: "database" });
    expect(screen.getByText("Outbound — publish")).toBeInTheDocument();
  });

  it("each direction can be switched off independently", async () => {
    const f = routeFetch(base({ "PUT /mes/config": (b) => ({ body: { ...STATUS, publish_enabled: b.publish_enabled } }) }));
    render(<ConfigMes />);
    fireEvent.click(await screen.findByLabelText("outbound enabled"));
    await waitFor(() => expect(screen.getByText(/Outbound is off — nothing is sent/)).toBeInTheDocument());
    const put = f.mock.calls.find(([u, o]: any) => String(u) === "/mes/config" && o?.method === "PUT")!;
    expect(JSON.parse((put[1] as any).body)).toEqual({ publish_enabled: false });
    expect(screen.queryByText(/Inbound is off/)).not.toBeInTheDocument();
  });

  it("falls back to typing when databases can't be listed", async () => {
    const f = routeFetch(base({
      "POST /mes/db/databases": { body: { ok: false, items: [], detail: "permission denied" } },
    }));
    render(<ConfigMes />);
    const card = (await screen.findByText("Inbound — gate")).closest(".MuiPaper-root") as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "Database" }));
    expect(await within(card).findByText(/Couldn't list databases \(permission denied\) — type the name\./)).toBeInTheDocument();
    fireEvent.change(within(card).getByLabelText("Database"), { target: { value: "MesPlant" } });
    fireEvent.click(within(card).getByRole("button", { name: "Save inbound" }));
    await waitFor(() => expect(f.mock.calls.some(([u, o]: any) => String(u) === "/mes/db-config" && o?.method === "PUT")).toBe(true));
    const put = f.mock.calls.find(([u, o]: any) => String(u) === "/mes/db-config" && o?.method === "PUT")!;
    const sent = JSON.parse((put[1] as any).body).inbound;
    expect(sent.database).toBe("MesPlant");
    expect(sent.connection).toEqual({ provider: "mysql", host: "mes-db", port: 3306, user: "u" });   // no password sent when none typed
  });

  it("offers a list when listing works", async () => {
    routeFetch(base());
    render(<ConfigMes />);
    const card = (await screen.findByText("Inbound — gate")).closest(".MuiPaper-root") as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "Database" }));
    const box = await within(card).findByLabelText("Database");
    fireEvent.mouseDown(box);
    fireEvent.keyDown(box, { key: "ArrowDown" });
    expect(await screen.findByRole("option", { name: "plant" })).toBeInTheDocument();
  });

  it("'Latest by' accepts a date column then a time column, in order", async () => {
    const f = routeFetch(base({
      "GET /mes/db-config": { body: { inbound: { connection: CONN, database: "mesdb", table: "units", serial_column: "serial", status_column: "status", allow_value: "PASS" }, outbound: {}, fields: FIELDS } },
      "POST /mes/db/tables": { body: { ok: true, items: ["units"], detail: "" } },
      "POST /mes/db/columns": { body: { ok: true, items: [{ name: "serial" }, { name: "status" }, { name: "d" }, { name: "t" }], detail: "" } },
      "POST /mes/db/values": { body: { ok: true, items: ["FAIL", "PASS"], detail: "" } },
    }));
    render(<ConfigMes />);
    const card = (await screen.findByText("Inbound — gate")).closest(".MuiPaper-root") as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "Latest by" }));
    const add = await within(card).findByRole("button", { name: "Add column" });
    fireEvent.click(add);
    fireEvent.click(within(card).getByRole("button", { name: "Add column" }));
    fireEvent.change(await within(card).findByLabelText("Column 1"), { target: { value: "d" } });
    fireEvent.change(within(card).getByLabelText("Column 2"), { target: { value: "t" } });
    expect(within(card).getByText("Newest by")).toBeInTheDocument();
    expect(within(card).getByText("then by")).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Save inbound" }));
    await waitFor(() => expect(f.mock.calls.some(([u, o]: any) => String(u) === "/mes/db-config" && o?.method === "PUT")).toBe(true));
    const put = f.mock.calls.find(([u, o]: any) => String(u) === "/mes/db-config" && o?.method === "PUT")!;
    expect(JSON.parse((put[1] as any).body).inbound.latest_by).toEqual(["d", "t"]);
  });

  it("'Try a serial' shows the gate's decision from the draft settings", async () => {
    routeFetch(base({
      "POST /mes/db/inbound/check": { body: { allowed: false, prior_result: "FAIL", detail: "MES status is 'FAIL', not 'PASS'", rows: ["FAIL"], matched: 1 } },
    }));
    render(<ConfigMes />);
    const card = (await screen.findByText("Inbound — gate")).closest(".MuiPaper-root") as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "Try a serial" }));
    fireEvent.change(await within(card).findByLabelText("Serial number"), { target: { value: "SN-FAIL" } });
    fireEvent.click(within(card).getByRole("button", { name: "Try" }));
    expect(await within(card).findByText("BLOCKED")).toBeInTheDocument();
    expect(within(card).getByText(/not 'PASS'/)).toBeInTheDocument();
  });

  it("outbound auto-matches columns of an existing table and flags a new one", async () => {
    routeFetch(base({
      "GET /mes/db-config": { body: { inbound: { connection: CONN }, outbound: { connection: CONN, database: "mesdb" }, fields: FIELDS } },
      "POST /mes/db/tables": { body: { ok: true, items: ["prod_log"], detail: "" } },
      "POST /mes/db/columns": { body: { ok: true, items: [{ name: "RUN_ID" }, { name: "Serial_No" }, { name: "Result" }], detail: "" } },
    }));
    render(<ConfigMes />);
    const card = (await screen.findByText("Outbound — publish")).closest(".MuiPaper-root") as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "Table" }));
    const table = await within(card).findByLabelText("Table");
    fireEvent.change(table, { target: { value: "prod_log" } });
    expect(await within(card).findByText("existing table")).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Columns" }));
    const row = (await within(card).findByText("serial_no *")).closest("tr") as HTMLElement;
    await waitFor(() => expect((within(row).getByRole("combobox") as HTMLInputElement).value).toBe("Serial_No"));
    const modelRow = within(card).getByText("model").closest("tr") as HTMLElement;
    expect((within(modelRow).getByRole("combobox") as HTMLInputElement).value).toBe("");      // optional, no match = skipped

    fireEvent.click(within(card).getByRole("button", { name: "Table" }));
    fireEvent.change(await within(card).findByLabelText("Table"), { target: { value: "brand_new" } });
    expect(await within(card).findAllByText(/new — will be created/)).not.toHaveLength(0);
  });
});
