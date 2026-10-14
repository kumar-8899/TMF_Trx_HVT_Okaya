import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { mockFetch } from "../../test/fetchMock";
import { ColorModeProvider } from "../../theme/ColorMode";
import { CalibrationPanel } from "./CalibrationPanel";

function Providers({ children }: { children: ReactNode }) {
  return <MemoryRouter><ColorModeProvider>{children}</ColorModeProvider></MemoryRouter>;
}

const SIGNALS = [
  { name: "ai_v", units: "V", readable: true, writable: false, factory: { gain: 1, offset: 0 }, calibration: null },
  { name: "ao_v", units: "V", readable: false, writable: true, factory: { gain: 1, offset: 0 },
    calibration: { gain: 2, offset: 0.5, by: "carol" } },
];

async function pick(name: string) {
  fireEvent.mouseDown(screen.getByLabelText("calibration signal"));
  fireEvent.click(await screen.findByRole("option", { name: new RegExp(name) }));
}

describe("CalibrationPanel", () => {
  it("captures an input point, previews the fit and applies it", async () => {
    const f = mockFetch({
      "GET /calibration/signals": { body: SIGNALS },
      "POST /calibration/ai_v/raw": { body: { raw: 3.0, scaled: 3.0 } },
      "POST /calibration/fit": { body: { gain: 2, offset: 0.5, n: 2, max_error: 0 } },
      "POST /calibration/ai_v/apply": { body: { gain: 2, offset: 0.5, controller: "reloaded" } },
    });
    render(<Providers><CalibrationPanel maintenanceOn={false} /></Providers>);
    await pick("ai_v");

    fireEvent.click(await screen.findByRole("button", { name: /capture raw reading/i }));
    await screen.findByText("raw: 3");
    fireEvent.change(screen.getByLabelText(/reference meter/i), { target: { value: "6.5" } });
    fireEvent.click(screen.getByRole("button", { name: /add point/i }));
    // second point
    fireEvent.click(screen.getByRole("button", { name: /capture raw reading/i }));
    await screen.findByText("raw: 3");
    fireEvent.change(screen.getByLabelText(/reference meter/i), { target: { value: "6.5" } });
    fireEvent.click(screen.getByRole("button", { name: /add point/i }));

    const fit = await screen.findByTestId("cal-fit");
    expect(within(fit).getByText(/gain 2 · offset 0.5/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /apply calibration/i }));
    await screen.findByText(/live now, no restart/i);
    const apply = f.mock.calls.find((c: any[]) => String(c[0]).endsWith("/calibration/ai_v/apply"));
    expect(JSON.parse(apply[1].body).points).toHaveLength(2);
  });

  it("an output signal needs maintenance mode to drive; shows the active calibration", async () => {
    mockFetch({ "GET /calibration/signals": { body: SIGNALS } });
    const { rerender } = render(<Providers><CalibrationPanel maintenanceOn={false} /></Providers>);
    await pick("ao_v");
    expect(await screen.findByText(/calibrated: gain 2, offset 0.5 · carol/)).toBeTruthy();
    expect(screen.getByText(/enter maintenance mode to drive an output/i)).toBeTruthy();
    expect((screen.getByRole("button", { name: /drive output/i }) as HTMLButtonElement).disabled).toBe(true);
    rerender(<Providers><CalibrationPanel maintenanceOn={true} /></Providers>);
    await waitFor(() => expect(screen.queryByText(/enter maintenance mode to drive/i)).toBeNull());
  });

  it("surfaces a pending controller reload instead of claiming success", async () => {
    mockFetch({
      "GET /calibration/signals": { body: SIGNALS },
      "DELETE /calibration/ao_v": { body: { controller: "pending", detail: "st1 is running — saved, applies after the run" } },
    });
    window.confirm = () => true;
    render(<Providers><CalibrationPanel maintenanceOn={true} /></Providers>);
    await pick("ao_v");
    fireEvent.click(await screen.findByRole("button", { name: /reset to factory/i }));
    await screen.findByText(/applies after the run/i);
  });

  it("shows a load failure rather than an empty panel", async () => {
    mockFetch({ "GET /calibration/signals": { status: 503, body: { detail: "bridge down" } } });
    render(<Providers><CalibrationPanel maintenanceOn={false} /></Providers>);
    await waitFor(() => expect(document.body.textContent).toMatch(/bridge down|503|error/i));
  });
});
