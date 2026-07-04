import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { AuthProvider } from "../auth/AuthContext";
import { mockFetch } from "../test/fetchMock";
import { Login } from "./Login";

function renderLogin() {
  return render(
    <MemoryRouter><AuthProvider><Login /></AuthProvider></MemoryRouter>,
  );
}

describe("Login", () => {
  beforeEach(() => localStorage.clear());

  it("submits credentials to /auth/login", async () => {
    const f = mockFetch({
      "POST /auth/login": { body: { token: "t", expires: 1, principal: { username: "a", role: "r", permissions: [] } } },
    });
    renderLogin();
    await userEvent.type(screen.getByLabelText("username"), "admin");
    await userEvent.type(screen.getByLabelText("password"), "admin");
    await userEvent.click(screen.getByRole("button", { name: /log in/i }));
    await waitFor(() => expect(f).toHaveBeenCalled());
    // useBranding fires a GET /branding on mount — find the login call explicitly.
    const call = (f as any).mock.calls.find(([u]: [string]) => String(u) === "/auth/login");
    expect(call).toBeTruthy();
    const [url, opts] = call;
    expect(url).toBe("/auth/login");
    expect(JSON.parse(opts.body)).toEqual({ username: "admin", credential: { password: "admin" } });
  });

  it("shows the error body on bad credentials", async () => {
    mockFetch({ "POST /auth/login": { status: 401, body: { title: "invalid credentials", status: 401 } } });
    renderLogin();
    await userEvent.type(screen.getByLabelText("username"), "admin");
    await userEvent.type(screen.getByLabelText("password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: /log in/i }));
    await waitFor(() => expect(screen.getByText("invalid credentials")).toBeInTheDocument());
  });
});
