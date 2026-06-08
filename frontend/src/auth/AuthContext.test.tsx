import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { mockFetch } from "../test/fetchMock";
import { AuthProvider, useAuth } from "./AuthContext";

function Probe() {
  const { principal, login, logout, can } = useAuth();
  return (
    <div>
      <div data-testid="user">{principal ? principal.username : "anon"}</div>
      <div data-testid="canusers">{String(can("AUTH.MANAGE_USERS"))}</div>
      <button onClick={() => login("admin", "admin")}>login</button>
      <button onClick={logout}>logout</button>
    </div>
  );
}

const LOGIN_OK = {
  body: { token: "t1", expires: 1, principal: { username: "admin", role: "super_admin", permissions: ["*"] } },
};

describe("AuthContext", () => {
  beforeEach(() => localStorage.clear());

  it("login stores principal + permissions; logout clears", async () => {
    mockFetch({ "POST /auth/login": LOGIN_OK, "POST /auth/logout": { body: { ok: true } } });
    render(<AuthProvider><Probe /></AuthProvider>);
    expect(screen.getByTestId("user")).toHaveTextContent("anon");

    await userEvent.click(screen.getByText("login"));
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("admin"));
    expect(screen.getByTestId("canusers")).toHaveTextContent("true"); // "*" grants
    expect(localStorage.getItem("tmf.token")).toBe("t1");

    await userEvent.click(screen.getByText("logout"));
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("anon"));
    expect(localStorage.getItem("tmf.token")).toBeNull();
  });

  it("revalidates a stored token on boot via /auth/me", async () => {
    localStorage.setItem("tmf.token", "stored");
    mockFetch({ "GET /auth/me": { body: { username: "bob", role: "operator", permissions: ["TEST.RUN"] } } });
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("bob"));
    expect(screen.getByTestId("canusers")).toHaveTextContent("false");
  });
});
