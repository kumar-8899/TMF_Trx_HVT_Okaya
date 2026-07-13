import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AuthProvider } from "../../auth/AuthContext";
import { mockFetch } from "../../test/fetchMock";
import { InstrumentControlPanel } from "./InstrumentControlPanel";

function wrap(node: React.ReactNode) {
  return <MemoryRouter><AuthProvider>{node}</AuthProvider></MemoryRouter>;
}

const CATALOG = {
  capabilities: {
    power_source: {
      label: "Power source",
      methods: [
        { method: "set_voltage", kind: "set", label: "Set voltage", args: [{ name: "volts", type: "number", unit: "V" }] },
        { method: "output_enable", kind: "toggle", label: "Output", args: [{ name: "on", type: "bool" }] },
        { method: "measure_voltage", kind: "read", label: "Measured voltage", args: [], unit: "V" },
      ],
    },
    analog_input: {
      label: "Analog input",
      methods: [{ method: "read_voltage", kind: "read", label: "Read voltage", args: [{ name: "channel", type: "int" }], unit: "V" }],
    },
    resistance: {
      label: "Resistance",
      methods: [{ method: "measure_resistance", kind: "read", label: "Measure resistance", args: [{ name: "channel", type: "int" }], unit: "Ω" }],
    },
  },
  base_actions: [
    { method: "safe_state", kind: "action", label: "Safe state", severity: "warning" },
    { method: "emergency_disable", kind: "action", label: "Emergency disable", severity: "error" },
  ],
};

const routes = () => ({
  // Config → Instruments is the source of the Test Bench list (owner=python)
  "GET /config/instruments": { body: [{ id: "psu1", label: "PSU 1", owner: "python", library: "tenma_72_13360", simulated: false, enabled: true }] },
  // the variable engine supplies live state
  "GET /variables/instances": { body: [{ id: "psu1", library: "tenma_72_13360", capabilities: ["power_source"], state: "connected", simulated: false }] },
  "GET /variables/capabilities": { body: CATALOG },
  "GET /variables/libraries": { body: { libraries: [] } },
  "POST /variables/instances/psu1/call": { body: { instance: "psu1", method: "set_voltage", result: null } },
});

describe("InstrumentControlPanel", () => {
  it("renders capability controls from the catalog", async () => {
    mockFetch(routes());
    render(wrap(<InstrumentControlPanel embedded />));
    expect(await screen.findByText("Set voltage")).toBeInTheDocument();
    expect(await screen.findByText("Measured voltage")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /emergency disable/i })).toBeInTheDocument();
  });

  it("posts {method, args} on a set command", async () => {
    const fetch = mockFetch(routes());
    render(wrap(<InstrumentControlPanel embedded />));
    const volts = await screen.findByLabelText(/volts/i);
    await userEvent.clear(volts);
    await userEvent.type(volts, "2.5");
    await userEvent.click(await screen.findByRole("button", { name: /^apply$/i }));
    await waitFor(() => {
      const call = (fetch.mock.calls as any[]).find(
        ([url, opts]) => String(url) === "/variables/instances/psu1/call" && opts?.method === "POST",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(call[1].body)).toEqual({ method: "set_voltage", args: [2.5] });
    });
  });

  it("enables commands on a connected instrument (no maintenance gate)", async () => {
    mockFetch(routes());
    render(wrap(<InstrumentControlPanel embedded />));
    expect(await screen.findByRole("button", { name: /^apply$/i })).not.toBeDisabled();
    expect(await screen.findByRole("button", { name: /safe state/i })).not.toBeDisabled();
  });

  it("lists a config-page instrument not yet loaded and marks it restart-pending", async () => {
    mockFetch({
      "GET /config/instruments": { body: [{ id: "psu2", label: "PSU 2", owner: "python", library: "tenma_72_13360", enabled: true }] },
      "GET /variables/instances": { body: [] },   // engine has not built it (added after boot)
      "GET /variables/capabilities": { body: CATALOG },
      "GET /variables/libraries": { body: { libraries: [{ library_id: "tenma_72_13360", capabilities: ["power_source"] }] } },
    });
    render(wrap(<InstrumentControlPanel embedded />));
    expect(await screen.findByText(/restart the app to load it/i)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /^apply$/i })).toBeDisabled();
  });

  it("ignores LabVIEW-owned instruments", async () => {
    mockFetch({
      "GET /config/instruments": { body: [
        { id: "psu1", label: "PSU 1", owner: "python", library: "tenma_72_13360", enabled: true },
        { id: "lv1", label: "LV Meter", owner: "labview", transport: "visa", enabled: true },
      ] },
      "GET /variables/instances": { body: [{ id: "psu1", library: "tenma_72_13360", capabilities: ["power_source"], state: "connected" }] },
      "GET /variables/capabilities": { body: CATALOG },
      "GET /variables/libraries": { body: { libraries: [] } },
    });
    render(wrap(<InstrumentControlPanel embedded />));
    expect(await screen.findByText("PSU 1")).toBeInTheDocument();
    expect(screen.queryByText("LV Meter")).not.toBeInTheDocument();
  });

  it("renders one control group per capability for a composite instrument", async () => {
    mockFetch({
      "GET /config/instruments": { body: [{ id: "dmm1", label: "DAQ6510", owner: "python", library: "keithley_daq6510", enabled: true }] },
      "GET /variables/instances": { body: [{ id: "dmm1", library: "keithley_daq6510", capabilities: ["analog_input", "resistance"], state: "connected" }] },
      "GET /variables/capabilities": { body: CATALOG },
      "GET /variables/libraries": { body: { libraries: [] } },
      "POST /variables/instances/dmm1/call": { body: { instance: "dmm1", method: "read_voltage", result: 1.23 } },
    });
    render(wrap(<InstrumentControlPanel embedded />));
    // a section (group) per declared capability
    expect(await screen.findByText("Analog input")).toBeInTheDocument();
    expect(await screen.findByText("Resistance")).toBeInTheDocument();
    expect(await screen.findByText("Read voltage")).toBeInTheDocument();
    expect(await screen.findByText("Measure resistance")).toBeInTheDocument();
  });
});
