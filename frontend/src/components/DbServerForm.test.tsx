import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { mockFetch } from "../test/fetchMock";
import { DbServerForm } from "./DbServerForm";

function renderForm(value: any, onChange = vi.fn()) {
  return render(<DbServerForm value={value} onChange={onChange} password="" onPassword={() => {}} />);
}

/** The 2nd combobox (the 1st is Provider) - it appears once /system/odbc-drivers has answered. */
async function driverSelect() {
  await waitFor(() => expect(screen.getAllByRole("combobox")).toHaveLength(2));
  return screen.getAllByRole("combobox")[1];
}

describe("DbServerForm - SQL Server ODBC driver (Okaya C9)", () => {
  it("offers the drivers installed on this PC, with 'newest installed' as the blank choice", async () => {
    mockFetch({ "GET /system/odbc-drivers": { body: {
      drivers: ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"],
      default: "ODBC Driver 18 for SQL Server" } } });
    const onChange = vi.fn();
    renderForm({ provider: "sqlserver", host: "h" }, onChange);
    fireEvent.mouseDown(await driverSelect());
    expect(await screen.findByRole("option", { name: /Newest installed \(ODBC Driver 18/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: "SQL Server" }));
    expect(onChange).toHaveBeenCalledWith({ odbc_driver: "SQL Server" });
  });

  it("marks a saved driver that is not installed on this PC", async () => {
    mockFetch({ "GET /system/odbc-drivers": { body: { drivers: ["SQL Server"], default: "SQL Server" } } });
    renderForm({ provider: "sqlserver", host: "h", odbc_driver: "ODBC Driver 18 for SQL Server" });
    fireEvent.mouseDown(await driverSelect());
    expect(await screen.findByRole("option", { name: /ODBC Driver 18 for SQL Server \(not installed here\)/ })).toBeInTheDocument();
  });

  it("falls back to a free-text field when the list is empty or unavailable", async () => {
    mockFetch({ "GET /system/odbc-drivers": { body: { drivers: [], default: null } } });
    renderForm({ provider: "sqlserver", host: "h" });
    const box = await screen.findByLabelText("ODBC driver");
    await waitFor(() => expect(box.tagName).toBe("INPUT"));
    expect(screen.queryByRole("combobox", { name: "ODBC driver" })).not.toBeInTheDocument();
  });

  it("MySQL has no driver field and asks for no driver list", async () => {
    const f = mockFetch({});
    renderForm({ provider: "mysql", host: "h" });
    expect(screen.queryByLabelText("ODBC driver")).not.toBeInTheDocument();
    expect((f as any).mock.calls.some(([u]: [string]) => String(u).includes("odbc-drivers"))).toBe(false);
  });
});
