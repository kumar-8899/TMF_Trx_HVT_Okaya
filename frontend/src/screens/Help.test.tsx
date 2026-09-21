import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { Help } from "./Help";

const TREE = [
  { section: "Getting started", audience: "user", pages: [{ id: "user-getting-started", title: "Getting started", route: "/", audience: "user" }] },
  { section: "Operations", audience: "user", pages: [{ id: "user-recipes", title: "Recipes", route: "/recipes", audience: "user" }] },
  { section: "Start here", audience: "dev", pages: [{ id: "dev-guide-start", title: "Developer Hub", route: null, audience: "dev" }] },
];
const DOCS: Record<string, string> = {
  "user-getting-started": "# Getting started body",
  "user-recipes": "# Recipes body",
  "dev-guide-start": "# Developer Hub body\n\n## Pick your path\n",
};

function mockApi() {
  return vi.spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === "/help/index") return TREE;
    const m = /^\/help\/page\/(.+)$/.exec(path);
    if (m) return { id: m[1], title: m[1], markdown: DOCS[m[1]] };
    return [];
  });
}

function renderAt(url: string) {
  return render(<MemoryRouter initialEntries={[url]}><Help /></MemoryRouter>);
}

// Cold module load (MUI) makes the first render slow on a busy machine — give async queries room.
const SLOW = { timeout: 15000 };

afterEach(() => vi.restoreAllMocks());

describe("Help screen", () => {
  it("opens the first user page when no ?page= is given", { timeout: 30000 }, async () => {
    const get = mockApi();
    renderAt("/help");
    expect(await screen.findByRole("heading", { name: "Getting started body" }, SLOW)).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/help/page/user-getting-started");
  });

  it("deep-links to the page named in ?page=", async () => {
    mockApi();
    renderAt("/help?page=user-recipes");
    expect(await screen.findByRole("heading", { name: "Recipes body" }, SLOW)).toBeInTheDocument();
  });

  it("deep-linking to a developer page switches to the Developer audience", async () => {
    mockApi();
    renderAt("/help?page=dev-guide-start#pick-your-path");
    expect(await screen.findByRole("heading", { name: "Developer Hub body" }, SLOW)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Developer" })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByText("Start here")).toBeInTheDocument();          // dev sidebar section shown
    expect(document.getElementById("pick-your-path")).not.toBeNull();     // heading anchor exists
  });

  it("hides the Developer toggle when the backend returns no developer pages (built station)", async () => {
    vi.spyOn(api, "get").mockImplementation(async (path: string) =>
      path === "/help/index" ? TREE.filter((s) => s.audience === "user")
        : { id: "x", title: "x", markdown: "# body" });
    renderAt("/help");
    await screen.findByRole("heading", { name: "body" }, SLOW);
    expect(screen.queryByRole("button", { name: "Developer" })).not.toBeInTheDocument();
  });
});
