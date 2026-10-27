import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockFetch } from "../../../test/fetchMock";
import { OkayaMesPage } from "./OkayaMesPage";

const CFG = { enabled: false, station_name: "HV Testing", database: "okaya", table: "txr_testtable",
  connection: { provider: "sqlserver", host: "mes01", port: 1433, user: "sa", has_password: true } };

const routes = (over: Record<string, any> = {}) => ({
  "GET /okaya-mes/config": { body: CFG },
  "GET /okaya-mes/status": { body: { enabled: false, ready: true, problem: null, table: "txr_testtable", failed_pushes: 0 } },
  "GET /okaya-mes/alerts": { body: { items: [], count: 0 } },
  "GET /system/odbc-drivers": { body: { drivers: [] } },
  "POST /okaya-mes/db/databases": { body: { ok: true, items: ["okaya"], detail: "" } },
  "POST /okaya-mes/db/tables": { body: { ok: true, items: ["txr_testtable"], detail: "" } },
  ...over,
});

const posted = (fetch: any, path: string, method = "POST") =>
  (fetch.mock.calls as any[]).filter(([u, o]) => String(u) === path && (o?.method ?? "GET") === method)
    .map(([, o]) => (o?.body ? JSON.parse(o.body) : null));

describe("OkayaMesPage", () => {
  it("explains a missing module (404) instead of a bare Not Found", async () => {
    mockFetch({});                                         // every /okaya-mes/* call -> 404, as when the module isn't loaded
    render(<OkayaMesPage />);
    expect(await screen.findByText(/okaya_mes module is not loaded/i)).toBeInTheDocument();
    expect(screen.getByText(/enable_okaya_mes\.ps1/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^save$/i })).not.toBeInTheDocument();    // no half-working form
  });

  it("loads the saved settings and never shows a password", async () => {
    mockFetch(routes());
    render(<OkayaMesPage />);
    expect(await screen.findByDisplayValue("mes01")).toBeInTheDocument();
    expect(screen.getByDisplayValue("HV Testing")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/unchanged/)).toHaveValue("");           // blank = keep the stored one
    // the target survives page load (a freeSolo Autocomplete can reset its input on mount)
    expect(screen.getByRole("combobox", { name: /database/i })).toHaveValue("okaya");
    expect(screen.getByRole("combobox", { name: /table/i })).toHaveValue("txr_testtable");
  });

  it("saves without a password when none was typed, and with one when it was", async () => {
    const fetch = mockFetch(routes({ "PUT /okaya-mes/config": { body: CFG } }));
    render(<OkayaMesPage />);
    const station = await screen.findByDisplayValue("HV Testing");
    await userEvent.clear(station);
    await userEvent.type(station, "HV Bench 2");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(posted(fetch, "/okaya-mes/config", "PUT")).toHaveLength(1));
    const first = posted(fetch, "/okaya-mes/config", "PUT")[0];
    expect(first.station_name).toBe("HV Bench 2");
    expect("password" in first.connection).toBe(false);

    await userEvent.type(screen.getByPlaceholderText(/unchanged/), "s3cret");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(posted(fetch, "/okaya-mes/config", "PUT")).toHaveLength(2));
    expect(posted(fetch, "/okaya-mes/config", "PUT")[1].connection.password).toBe("s3cret");
  });

  it("names the missing columns when the table does not fit", async () => {
    mockFetch(routes({ "POST /okaya-mes/table/check": { body: {
      ok: false, exists: true, missing: ["failed_test", "model_name"], detail: "missing column(s): failed_test, model_name" } } }));
    render(<OkayaMesPage />);
    await userEvent.click(await screen.findByRole("button", { name: /check table/i }));
    expect(await screen.findByText("failed_test, model_name", { selector: "span" })).toBeInTheDocument();   // the warning
    expect(screen.getAllByText(/missing column\(s\)/i)).toHaveLength(2);                                   // chip + warning
  });

  it("lists failed deliveries with Retry and Dismiss", async () => {
    const fetch = mockFetch(routes({
      "GET /okaya-mes/alerts": { body: { count: 1, items: [{ run_id: "R9", serial: "SN-9", result: "FAIL", error: "timed out", ts: 1 }] } },
      "POST /okaya-mes/alerts/R9/retry": { body: { ok: true, detail: "delivered (SN-9)" } },
    }));
    render(<OkayaMesPage />);
    expect(await screen.findByText("SN-9")).toBeInTheDocument();
    expect(screen.getByText("timed out")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(posted(fetch, "/okaya-mes/alerts/R9/retry")).toHaveLength(1));
    expect(await screen.findByText(/Delivered: delivered \(SN-9\)/)).toBeInTheDocument();
  });

  it("previews the exact row for a run, showing NULL for empty columns", async () => {
    mockFetch(routes({ "GET /okaya-mes/preview/R1": { body: {
      run_id: "R1", columns: ["serial_no", "failed_test"], row: { serial_no: "SN-1", failed_test: null } } } }));
    render(<OkayaMesPage />);
    await userEvent.type(await screen.findByLabelText(/run id/i), "R1");
    await userEvent.click(screen.getByRole("button", { name: /preview row/i }));
    expect(await screen.findByText("SN-1")).toBeInTheDocument();
    expect(screen.getByText("NULL")).toBeInTheDocument();
  });
});
