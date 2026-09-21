import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { helpLink } from "../components/help/Markdown";
import { Portal } from "./Portal";

vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ can: () => true }) }));

const TREE = [
  { section: "Getting started", audience: "user", pages: [{ id: "user-getting-started", title: "Getting started", route: "/", audience: "user" }] },
  { section: "This app", audience: "user", pages: [{ id: "app-acme-wiring", title: "Wiring the bench", route: null, audience: "user" }] },
  { section: "Start here", audience: "dev", pages: [{ id: "dev-guide-start", title: "Developer Hub", route: null, audience: "dev" }] },
];
const PAGES: Record<string, string> = {
  "user-getting-started": "# Getting started\n\nSee [wiring](help:app-acme-wiring).",
  "app-acme-wiring": "# Wiring\n\nConnect the PSU.",
};

function Where() {
  const l = useLocation();
  return <div data-testid="where">{l.pathname + l.search}</div>;
}
function renderAt(url: string) {
  return render(<MemoryRouter initialEntries={[url]}><Portal /><Where /></MemoryRouter>);
}
function mockApi() {
  return vi.spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === "/help/index") return TREE;
    if (path === "/portal/library") return [];
    const m = /^\/help\/page\/(.+)$/.exec(path);
    return m ? { id: m[1], title: m[1], markdown: PAGES[m[1]] } : [];
  });
}
const SLOW = { timeout: 15000 };
afterEach(() => vi.restoreAllMocks());

describe("Portal", () => {
  it("opens on the Manual tab, user pages only (no Developer toggle even for a developer)", async () => {
    mockApi();
    renderAt("/portal");
    expect(await screen.findByRole("heading", { name: "Getting started" }, SLOW)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Developer" })).not.toBeInTheDocument();
    expect(screen.queryByText("Start here")).not.toBeInTheDocument();          // dev section not offered in the portal
    expect(screen.getByText("Wiring the bench")).toBeInTheDocument();          // app-owned page appears under "This app"
    expect(screen.getByText("This app")).toBeInTheDocument();
  });

  it("switches to the Library tab and back", async () => {
    mockApi();
    renderAt("/portal");
    await screen.findByRole("heading", { name: "Getting started" }, SLOW);
    fireEvent.click(screen.getByRole("tab", { name: "Library" }));
    expect(await screen.findByLabelText("search library")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/portal?tab=library");
    fireEvent.click(screen.getByRole("tab", { name: "Manual" }));
    expect(await screen.findByRole("heading", { name: "Getting started" })).toBeInTheDocument();
  });

  it("keeps help: links inside the portal instead of jumping to /help", async () => {
    mockApi();
    renderAt("/portal?tab=manual");
    fireEvent.click(await screen.findByText("wiring", { selector: "a" }, SLOW));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/portal?tab=manual&page=app-acme-wiring"));
    expect(await screen.findByRole("heading", { name: "Wiring" })).toBeInTheDocument();
  });

  it("helpLink builds both portal and full-help URLs", () => {
    expect(helpLink("/help", "user-x", "top")).toBe("/help?page=user-x#top");
    expect(helpLink("/portal?tab=manual", "user-x")).toBe("/portal?tab=manual&page=user-x");
  });
});
