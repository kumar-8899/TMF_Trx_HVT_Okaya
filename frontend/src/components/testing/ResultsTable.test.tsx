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
    expect(screen.getByText("Output Voltage")).toBeInTheDocument();
    expect(screen.getByText("Output Current")).toBeInTheDocument();
    expect(screen.queryByText("Enable Output")).not.toBeInTheDocument();
    expect(screen.queryByText("Close Relay 1")).not.toBeInTheDocument();
    expect(screen.getByText(/Show setup steps \(2 hidden\)/)).toBeInTheDocument();
  });

  it("reveals setup steps when the toggle is switched on, without dropping anything", async () => {
    render(<ResultsTable rows={[...setup, ...graded]} />);
    await userEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByText("Enable Output")).toBeInTheDocument();
    expect(screen.getByText("Close Relay 1")).toBeInTheDocument();
    expect(screen.getByText("Output Voltage")).toBeInTheDocument();   // graded rows still there
    expect(screen.getByText("Showing setup steps")).toBeInTheDocument();
  });

  it("shows no toggle at all when there are no INFO rows to hide", () => {
    render(<ResultsTable rows={graded} />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.getByText("Output Voltage")).toBeInTheDocument();
  });

  it("distinguishes truly empty from all-hidden-as-setup-steps", () => {
    const { rerender } = render(<ResultsTable rows={[]} />);
    expect(screen.getByText("No results yet.")).toBeInTheDocument();

    rerender(<ResultsTable rows={setup} />);
    expect(screen.getByText(/No graded results yet \(2 setup steps recorded\)/)).toBeInTheDocument();
  });

  // ---- display formatting (framework-fix-prompt.md Issue 8) ----------------

  it("rounds a long-precision float measured value to 2 decimal places", () => {
    render(<ResultsTable rows={[
      { serial_no: 1, test_name: "vac_reading", measured: 230.09676878456958, expected: 230, result: "PASS" },
    ]} />);
    expect(screen.getByText("230.10")).toBeInTheDocument();
    expect(screen.queryByText("230.09676878456958")).not.toBeInTheDocument();
  });

  it("humanizes a snake_case test_name to Title Case", () => {
    render(<ResultsTable rows={[
      { serial_no: 1, test_name: "no_load_current_270", measured: 1, result: "PASS" },
    ]} />);
    expect(screen.getByText("No Load Current 270")).toBeInTheDocument();
  });

  it("leaves an already human-readable test_name unchanged", () => {
    render(<ResultsTable rows={[
      { serial_no: 1, test_name: "No Load Current 270", measured: 1, result: "PASS" },
    ]} />);
    expect(screen.getByText("No Load Current 270")).toBeInTheDocument();
  });

  it("does not mangle a range-string expected value with the numeric formatter", () => {
    render(<ResultsTable rows={[
      { serial_no: 1, test_name: "vbus", expected: "229.0–231.0", measured: 230.5, result: "PASS" },
    ]} />);
    expect(screen.getByText("229.0–231.0")).toBeInTheDocument();
    expect(screen.getByText("230.50")).toBeInTheDocument();
  });
});
