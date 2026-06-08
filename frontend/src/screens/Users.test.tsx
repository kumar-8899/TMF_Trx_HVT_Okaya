import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockFetch } from "../test/fetchMock";
import { Users } from "./Users";

describe("Users admin", () => {
  it("lists users", async () => {
    mockFetch({ "GET /auth/users": { body: [{ username: "admin", role: "super_admin", state: "ACTIVE" }] } });
    render(<Users />);
    await waitFor(() => expect(screen.getByText("admin")).toBeInTheDocument());
    expect(screen.getByText("ACTIVE")).toBeInTheDocument();
  });

  it("locks a user", async () => {
    const fetchSpy = mockFetch({
      "GET /auth/users": { body: [{ username: "op", role: "operator", state: "ACTIVE" }] },
      "POST /auth/users/op/lock": { body: { username: "op", state: "LOCKED" } },
    });
    render(<Users />);
    await waitFor(() => expect(screen.getByText("op")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /^lock$/i }));
    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining("/auth/users/op/lock"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
