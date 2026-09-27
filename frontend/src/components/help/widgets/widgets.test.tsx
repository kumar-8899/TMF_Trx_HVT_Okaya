import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../../api/client";
import { ChecklistWidget } from "./Checklist";
import { DiagramWidget } from "./Diagrams";
import { ChangelogWidget, FactsWidget, PermissionsMatrixWidget } from "./FactsWidgets";
import { resetFactsCache, type Facts } from "./facts";
import { classifyPath } from "./Ownership";
import { SkillPickerWidget } from "./SkillPicker";

const FACTS: Facts = {
  schema_version: 1,
  framework: { name: "Super_Test_App", version: "9.9.9" },
  releases: [
    { version: "9.9.9", date: "2026-01-02", bump: "MINOR", summary: "New thing (MINOR).", body: "- did it" },
    { version: "9.9.8", date: "2026-01-01", bump: "PATCH", summary: "Fix thing (PATCH).", body: "- fixed" },
  ],
  modules: [{
    id: "recipe", display_name: "Recipe", description: null, version: "1.0.0", contract_version: 1,
    entitlement_key: "recipe", variants: ["default"], api_prefix: "/recipes", core_dependencies: ["db"],
    contract_dependencies: [], permissions_used: ["RECIPE.VIEW"], routes: [],
  }],
  core: { routes: [] },
  permissions: [
    { key: "RECIPE.VIEW", domain: "Recipe", label: "View recipes", description: "" },
    { key: "AUTH.MANAGE_USERS", domain: "Auth", label: "Manage users", description: "" },
  ],
  roles: { super_admin: ["AUTH.*", "RECIPE.*"], operator: ["RECIPE.VIEW"] },
  step_types: [], capabilities: [], controller_ops: [], frontend_routes: [],
  skills: [{ name: "clone-test-app", description: "Clone an existing app. More text." }],
};

beforeEach(() => {
  resetFactsCache();
  vi.spyOn(api, "get").mockResolvedValue(FACTS);
});
afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

describe("classifyPath — the TEMPLATE.md §1 ownership boundary", () => {
  const fw = ["auth", "recipe", "runs"];
  it.each([
    ["app/acme_eol/recipes/main.json", "app"],
    ["instrument_libs/power/tenma.py", "app"],
    ["frontend/src/app/overrides/runs.tsx", "app"],
    ["labview/App/x.vi", "app"],
    ["backend/config/app.json", "app"],
    ["backend/modules/acme_eol/api.py", "app"],
    ["backend/modules/recipe/api.py", "framework"],
    ["backend/core/app.py", "framework"],
    ["frontend/src/screens/Runs.tsx", "framework"],
    ["controller/controller/serve.py", "framework"],
    ["backend\\core\\app.py", "framework"],               // Windows separators
    ["./app/acme/VERSION", "app"],
  ])("%s -> %s-owned", (path, owner) => {
    expect(classifyPath(path, fw)?.owner).toBe(owner);
  });
  it("returns null for empty input", () => expect(classifyPath("  ", fw)).toBeNull());
  it("tells you what to do for a framework file", () => {
    expect(classifyPath("backend/core/app.py", fw)?.advice).toMatch(/cut a release/);
  });
});

describe("SkillPicker", () => {
  it("routes a new app with a similar existing app to clone-test-app", async () => {
    render(<SkillPickerWidget />);
    fireEvent.click(screen.getByText(/Starting a brand-new application/));
    fireEvent.click(screen.getByText(/Yes — same\/overlapping/));
    expect(await screen.findByText("clone-test-app")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Clone an existing app/)).toBeInTheDocument());   // description from facts
  });
  it("routes an existing-app test to add-bench-test and can start over", () => {
    render(<SkillPickerWidget />);
    fireEvent.click(screen.getByText(/already exists/));
    fireEvent.click(screen.getByText(/A test or test sequence/));
    expect(screen.getByText("add-bench-test")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Start over"));
    expect(screen.getByText("What are you doing?")).toBeInTheDocument();
  });
});

describe("Checklist", () => {
  it("counts ticks and persists them per checklist", () => {
    const arg = "- Install Git\n- Clone the repos\n- Run the app";
    const { unmount } = render(<ChecklistWidget arg={arg} />);
    expect(screen.getByText("0/3")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    expect(screen.getByText("1/3")).toBeInTheDocument();
    unmount();
    render(<ChecklistWidget arg={arg} />);                 // remount = page revisit
    expect(screen.getByText("1/3")).toBeInTheDocument();
    expect((screen.getAllByRole("checkbox")[1] as HTMLInputElement).checked).toBe(true);
  });
});

describe("facts widgets", () => {
  it("renders the framework version and the module table from generated facts", async () => {
    render(<><FactsWidget arg="version" /><FactsWidget arg="modules" /></>);
    expect(await screen.findByText("v9.9.9")).toBeInTheDocument();
    expect(await screen.findByText("/recipes")).toBeInTheDocument();
  });

  it("expands role wildcards in the permission matrix like the backend does", async () => {
    render(<PermissionsMatrixWidget />);
    await screen.findByText("RECIPE.VIEW");
    const rows = screen.getAllByRole("row");
    const cells = (i: number) => Array.from(rows[i].querySelectorAll("td")).map((c) => c.textContent);
    expect(cells(1).slice(1)).toEqual(["●", "●"]);        // RECIPE.VIEW: super_admin (RECIPE.*), operator
    expect(cells(2).slice(1)).toEqual(["●", "·"]);        // AUTH.MANAGE_USERS: super_admin only
  });

  it("filters the changelog feed by bump type", async () => {
    render(<ChangelogWidget arg="" />);
    expect(await screen.findByText("New thing (MINOR).")).toBeInTheDocument();
    fireEvent.click(screen.getByText("PATCH", { selector: "button" }));
    expect(screen.queryByText("New thing (MINOR).")).not.toBeInTheDocument();
    expect(screen.getByText("Fix thing (PATCH).")).toBeInTheDocument();
  });

  it("explains itself when facts are unavailable (e.g. a fork missing the generated file)", async () => {
    (api.get as any).mockRejectedValue(new Error("no generated facts available"));
    render(<FactsWidget arg="modules" />);
    expect(await screen.findByText(/Generated facts unavailable/)).toBeInTheDocument();
  });
});

describe("diagrams", () => {
  it.each(["architecture", "boundary", "chain", "release"])("renders the %s diagram", (name) => {
    render(<MemoryRouter><DiagramWidget arg={name} /></MemoryRouter>);
    expect(screen.getByRole("img")).toBeInTheDocument();
  });
  it("reports an unknown diagram loudly", () => {
    render(<DiagramWidget arg="nope" />);
    expect(screen.getByText(/Unknown diagram/)).toBeInTheDocument();
  });
});
