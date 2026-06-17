import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AuthProvider } from "../auth/AuthContext";
import { mockFetch } from "../test/fetchMock";
import { Daq } from "./Daq";
import { Runs } from "./Runs";

function wrap(node: React.ReactNode) {
  return <MemoryRouter><AuthProvider>{node}</AuthProvider></MemoryRouter>;
}

describe("Daq", () => {
  it("reads a variable value", async () => {
    mockFetch({ "GET /variables/vbus_main/value": { body: { value: 264.0, ts: 1.0 } } });
    render(wrap(<Daq />));
    await userEvent.click(screen.getByRole("button", { name: /read/i }));
    await waitFor(() => expect(screen.getByText(/264/)).toBeInTheDocument());
  });

  it("sends the channel count to LabVIEW on stream start", async () => {
    // jsdom has no WebSocket; once running flips true useStream constructs one.
    (globalThis as any).WebSocket = class { close() {} };
    localStorage.setItem("tmf.token", "t");
    const fetch = mockFetch({
      "GET /auth/me": { body: { username: "op", role: "operator", permissions: ["TEST.RUN"] } },
      "POST /instruments/daq/ai/stream/start": { body: { ok: true } },
    });
    render(wrap(<Daq />));

    const channels = await screen.findByLabelText("ai-channels");
    await userEvent.clear(channels);
    await userEvent.type(channels, "4");
    const startButtons = await screen.findAllByRole("button", { name: /^start$/i });
    await userEvent.click(startButtons[0]); // AI start

    await waitFor(() => {
      const call = (fetch.mock.calls as any[]).find(
        ([url, opts]) =>
          String(url) === "/instruments/daq/ai/stream/start" && opts?.method === "POST",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(call[1].body)).toEqual({ channels: 4 });
    });
    localStorage.removeItem("tmf.token");
  });
});

describe("Runs", () => {
  it("lists run records", async () => {
    mockFetch({ "GET /runs": { body: [{ id: "R1", data: { status: "finished" } }] } });
    render(wrap(<Runs />));
    await waitFor(() => expect(screen.getByText("R1")).toBeInTheDocument());
    expect(screen.getByText("finished")).toBeInTheDocument();
  });
});
