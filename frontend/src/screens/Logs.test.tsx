import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockFetch } from "../test/fetchMock";
import { Logs } from "./Logs";

const ERRORS = {
  body: {
    items: [{ id: "e1", ts: 1700000000, summary: "[error] daq: boom",
              data: { level: "error", subsystem: "daq", message: "boom" } }],
    next_cursor: null, total: null,
  },
};
const ACTIONS = {
  body: {
    items: [{ id: "a1", ts: 1700000001, summary: "op1 recipe.save r1 -> success",
              data: { user: "op1", action: "recipe.save", result: "success" } }],
    next_cursor: null, total: null,
  },
};

describe("Logs viewer", () => {
  it("loads errors then switches to actions", async () => {
    mockFetch({ "GET /logs/errors": ERRORS, "GET /logs/actions": ACTIONS });
    render(<Logs />);
    await waitFor(() => expect(screen.getByText("[error] daq: boom")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("tab", { name: /actions/i }));
    await waitFor(() => expect(screen.getByText("op1 recipe.save r1 -> success")).toBeInTheDocument());
    expect(screen.getByText("op1")).toBeInTheDocument();
  });

  it("shows empty state when no records", async () => {
    mockFetch({ "GET /logs/errors": { body: { items: [], next_cursor: null, total: null } } });
    render(<Logs />);
    await waitFor(() => expect(screen.getByText("No records.")).toBeInTheDocument());
  });
});
