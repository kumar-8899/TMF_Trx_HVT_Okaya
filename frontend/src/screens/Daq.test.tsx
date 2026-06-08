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
});

describe("Runs", () => {
  it("lists run records", async () => {
    mockFetch({ "GET /runs": { body: [{ id: "R1", data: { status: "finished" } }] } });
    render(wrap(<Runs />));
    await waitFor(() => expect(screen.getByText("R1")).toBeInTheDocument());
    expect(screen.getByText("finished")).toBeInTheDocument();
  });
});
