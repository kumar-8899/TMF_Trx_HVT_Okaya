import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../test/fetchMock";
import { ReportExportControls } from "./ReportExportControls";

const CATALOG = {
  formats: [{ id: "xlsx", label: "Excel (.xlsx)", ext: "xlsx" }, { id: "tdms", label: "TDMS (.tdms)", ext: "tdms" }],
  fields: [
    { id: "expected", label: "Expected Value" }, { id: "measured", label: "Measured Value" },
    { id: "result", label: "Result" }, { id: "cycle", label: "Cycle Time" },
  ],
  columns: [],
};

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
  mockFetch({ "GET /reports/export/formats": { body: CATALOG } });
});

describe("ReportExportControls", () => {
  it("exports xlsx with every field by default, keeping the active filters", async () => {
    const onExport = vi.fn();
    render(<ReportExportControls query="model=AA&result=PASS" onExport={onExport} />);
    const btn = await screen.findByRole("button", { name: /Export \(all filtered\)/ });
    fireEvent.click(btn);
    const url = new URL(onExport.mock.calls[0][0], "http://x");
    expect(url.pathname).toBe("/reports/full/export");
    expect(url.searchParams.get("format")).toBe("xlsx");
    expect(url.searchParams.get("fields")).toBe("expected,measured,result,cycle");
    expect(url.searchParams.get("model")).toBe("AA");
  });

  it("drops an unticked field and sends the chosen format", async () => {
    const onExport = vi.fn();
    render(<ReportExportControls query="" onExport={onExport} />);
    fireEvent.click(await screen.findByRole("button", { name: /Test columns \(4\/4\)/ }));
    fireEvent.click(screen.getByLabelText("Result"));
    // the open popover is modal, so the page behind it is aria-hidden
    expect(screen.getByRole("button", { name: /Test columns \(3\/4\)/, hidden: true })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("presentation"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByLabelText("Result")).not.toBeInTheDocument());

    fireEvent.mouseDown(screen.getByLabelText("Export format"));
    fireEvent.click(await screen.findByRole("option", { name: "TDMS (.tdms)" }));
    fireEvent.click(screen.getByRole("button", { name: /Export \(all filtered\)/ }));
    const url = new URL(onExport.mock.calls[0][0], "http://x");
    expect(url.searchParams.get("format")).toBe("tdms");
    expect(url.searchParams.get("fields")).toBe("expected,measured,cycle");
  });

  it("disables Export when no test column is ticked", async () => {
    render(<ReportExportControls query="" onExport={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Test columns/ }));
    for (const f of CATALOG.fields) fireEvent.click(screen.getByLabelText(f.label));
    await waitFor(() => expect(screen.getByRole("button", { name: /Export \(all filtered\)/, hidden: true })).toBeDisabled());
  });

  it("restores the last selection", async () => {
    localStorage.setItem("tmf.reportExport", JSON.stringify({ format: "tdms", fields: ["measured"] }));
    render(<ReportExportControls query="" onExport={vi.fn()} />);
    expect(await screen.findByRole("button", { name: /Test columns \(1\/4\)/ })).toBeInTheDocument();
  });
});
