import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { AuthProvider } from "../auth/AuthContext";
import { mockFetch } from "../test/fetchMock";
import { ColorModeProvider } from "../theme/ColorMode";
import { Layout } from "./Layout";

function renderShell() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <ColorModeProvider><AuthProvider>
        <Routes><Route element={<Layout />}><Route path="/" element={<div>home</div>} /></Route></Routes>
      </AuthProvider></ColorModeProvider>
    </MemoryRouter>,
  );
}

const BRANDING = { name: "Acme Tester", short: "A", product: "Acme", tagline: "t",
  version: "1.31.0", framework_version: "1.31.0", app_version: "2.4.0" };

afterEach(() => localStorage.clear());

describe("Layout — Help + Portal merged, version in the footer (X6, X10)", () => {
  it("Portal is the one docs entry: no separate 'Help' nav item, no 'Relaunch to update', app version shown", async () => {
    localStorage.setItem("tmf.token", "t");
    mockFetch({
      "GET /auth/me": { body: { username: "op", role: "operator", permissions: ["PORTAL.VIEW", "HELP.VIEW", "TEST.RUN"] } },
      "GET /branding": { body: BRANDING },
      // a staged update would previously have rendered the relaunch chip at the foot of the menu
      "GET /update/offers": { body: { offers: [{ status: "apply_pending", version: "9.9.9", release_id: "r" }] } },
    });
    renderShell();
    expect(await screen.findByRole("link", { name: "Portal" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("nav-version")).toHaveTextContent("Version 2.4.0"));
    expect(screen.queryByRole("link", { name: "Help" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Developer docs" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Relaunch to update/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText("open help")).toBeInTheDocument();     // F1 context help is kept
  });

  it("a role that can read help but not open the Portal keeps a Help entry", async () => {
    localStorage.setItem("tmf.token", "t");
    mockFetch({
      "GET /auth/me": { body: { username: "v", role: "viewer", permissions: ["HELP.VIEW"] } },
      "GET /branding": { body: BRANDING },
    });
    renderShell();
    expect(await screen.findByRole("link", { name: "Help" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Portal" })).not.toBeInTheDocument();
  });

  it("super_admin on a source checkout gets 'Developer docs'; a built station (no dev pages) does not", async () => {
    localStorage.setItem("tmf.token", "t");
    mockFetch({
      "GET /auth/me": { body: { username: "root", role: "super_admin", permissions: ["PORTAL.VIEW", "HELP.VIEW"] } },
      "GET /branding": { body: BRANDING },
      "GET /help/index": { body: [{ section: "Start here", audience: "dev", pages: [] }] },
    });
    renderShell();
    expect(await screen.findByRole("link", { name: "Developer docs" })).toBeInTheDocument();
  });

  it("no developer docs in the index -> no Developer docs entry", async () => {
    localStorage.setItem("tmf.token", "t");
    mockFetch({
      "GET /auth/me": { body: { username: "root", role: "super_admin", permissions: ["PORTAL.VIEW", "HELP.VIEW"] } },
      "GET /branding": { body: BRANDING },
      "GET /help/index": { body: [{ section: "Getting started", audience: "user", pages: [] }] },
    });
    renderShell();
    await screen.findByRole("link", { name: "Portal" });
    await new Promise((r) => setTimeout(r, 100));
    expect(screen.queryByRole("link", { name: "Developer docs" })).not.toBeInTheDocument();
  });
});
