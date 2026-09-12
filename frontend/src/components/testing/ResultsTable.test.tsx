import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ResultsTable, type ResultRow } from "./ResultsTable";

const graded: ResultRow[] = [
  { serial_no: 1, test_name: "output_voltage", expected: "4–6", measured: 5, result: "PASS" },
  { serial_no: 2, test_name: "output_current", expected: "≤ 1", measured: 2, result: "FAIL" },
];
const setup: ResultRow[] = [
  { serial_no: 3, test_name: "enable_output", measured: true, result: "INFO" },
  { serial_no: 4, test_name: "close_relay_1", measured: true, result: "INFO" },
];

describe("ResultsTable", () => {
  it("hides INFO rows by default, showing only graded PASS/FAIL rows", () => {
    render(<ResultsTable rows={[...setup, ...graded]} />);
    expect(screen.getByText("output_voltage")).toBeInTheDocument();
    expect(screen.getByText("output_current")).toBeInTheDocument();
    expect(screen.queryByText("enable_output")).not.toBeInTheDocument();
    expect(screen.queryByText("close_relay_1")).not.toBeInTheDocument();
    expect(screen.getByText(/Show setup steps \(2 hidden\)/)).toBeInTheDocument();
  });

  it("reveals setup steps when the toggle is switched on, without dropping anything", async () => {
    render(<ResultsTable rows={[...setup, ...graded]} />);
    await userEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByText("enable_output")).toBeInTheDocument();
    expect(screen.getByText("close_relay_1")).toBeInTheDocument();
    expect(screen.getByText("output_voltage")).toBeInTheDocument();   // graded rows still there
    expect(screen.getByText("Showing setup steps")).toBeInTheDocument();
  });

  it("shows no toggle at all when there are no INFO rows to hide", () => {
    render(<ResultsTable rows={graded} />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.getByText("output_voltage")).toBeInTheDocument();
  });

  it("distinguishes truly empty from all-hidden-as-setup-steps", () => {
    const { rerender } = render(<ResultsTable rows={[]} />);
    expect(screen.getByText("No results yet.")).toBeInTheDocument();

    rerender(<ResultsTable rows={setup} />);
    expect(screen.getByText(/No graded results yet \(2 setup steps recorded\)/)).toBeInTheDocument();
  });
});
