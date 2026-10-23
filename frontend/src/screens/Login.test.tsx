import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

  it("default (picker off): free-text username box, nothing enumerated", async () => {
    mockFetch({ "GET /auth/login-options": { body: { user_picker: false, users: [] } } });
    renderLogin();
    await waitFor(() => expect(screen.getByLabelText("username")).toBeInTheDocument());
    expect(screen.getByLabelText("username").tagName).toBe("INPUT");      // a text field, not a select
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("picker on: username is a dropdown of the active users; the picked name is what is sent", async () => {
    const f = mockFetch({
      "GET /auth/login-options": { body: { user_picker: true, users: ["admin", "op"] } },
      "POST /auth/login": { body: { token: "t", expires: 1, principal: { username: "op", role: "operator", permissions: [] } } },
    });
    renderLogin();
    fireEvent.mouseDown(await screen.findByRole("combobox"));
    fireEvent.click(await screen.findByRole("option", { name: "op" }));
    await userEvent.type(screen.getByLabelText("password"), "oppass12");
    await userEvent.click(screen.getByRole("button", { name: /log in/i }));
    await waitFor(() => expect((f as any).mock.calls.some(([u]: [string]) => String(u) === "/auth/login")).toBe(true));
    const call = (f as any).mock.calls.find(([u]: [string]) => String(u) === "/auth/login");
    expect(JSON.parse(call[1].body)).toEqual({ username: "op", credential: { password: "oppass12" } });
  });

  it("falls back to free text if the options endpoint fails", async () => {
    mockFetch({ "GET /auth/login-options": { status: 500, body: {} } });
    renderLogin();
    await waitFor(() => expect(screen.getByLabelText("username").tagName).toBe("INPUT"));
  });

  it("shows the real app version bottom-right (app version wins over framework)", async () => {
    mockFetch({ "GET /branding": { body: { name: "Acme Tester", short: "A", product: "Acme", tagline: "t",
      version: "1.31.0", framework_version: "1.31.0", app_version: "2.4.0" } } });
    renderLogin();
    await waitFor(() => expect(screen.getByTestId("app-version")).toHaveTextContent("v2.4.0"));
    expect(screen.queryByText("v1.0.0")).not.toBeInTheDocument();        // the old hard-coded string
  });
});
