import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AuthProvider } from "../auth/AuthContext";
import { mockFetch } from "../test/fetchMock";
import { UserMenu } from "./UserMenu";

function Harness() {
  return (
    <MemoryRouter initialEntries={["/"]}>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<UserMenu />} />
          <Route path="/users" element={<div>Users page</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("UserMenu", () => {
  it("shows 'Manage users' for a principal with AUTH.MANAGE_USERS and navigates to /users", async () => {
    localStorage.setItem("tmf.token", "tok");
    mockFetch({
      "GET /auth/me": {
        body: { username: "admin", role: "super_admin", permissions: ["AUTH.MANAGE_USERS"] },
      },
    });
    render(<Harness />);
    await waitFor(() => expect(screen.getByLabelText("user menu")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("user menu"));
    const item = await screen.findByText("Manage users");
    fireEvent.click(item);
    await waitFor(() => expect(screen.getByText("Users page")).toBeInTheDocument());
    localStorage.removeItem("tmf.token");
  });

  it("hides 'Manage users' for a principal without AUTH.MANAGE_USERS", async () => {
    localStorage.setItem("tmf.token", "tok");
    mockFetch({
      "GET /auth/me": {
        body: { username: "op", role: "operator", permissions: ["TEST.RUN"] },
      },
    });
    render(<Harness />);
    await waitFor(() => expect(screen.getByLabelText("user menu")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("user menu"));
    await screen.findByText("Log out");   // menu is open
    expect(screen.queryByText("Manage users")).not.toBeInTheDocument();
    localStorage.removeItem("tmf.token");
  });
});
