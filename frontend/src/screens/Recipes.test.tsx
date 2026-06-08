import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AuthProvider } from "../auth/AuthContext";
import { mockFetch } from "../test/fetchMock";
import { RecipeDetail } from "./RecipeDetail";
import { RecipeEditor } from "./RecipeEditor";
import { Recipes } from "./Recipes";

describe("Recipes list", () => {
  it("renders recipe rows", async () => {
    mockFetch({ "GET /recipes": { body: [{ recipe_id: "inv", name: "Inverter", status: "active", latest_version: 2 }] } });
    render(<MemoryRouter><AuthProvider><Recipes /></AuthProvider></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("Inverter")).toBeInTheDocument());
    expect(screen.getByText("v2")).toBeInTheDocument();
  });
});

describe("RecipeEditor", () => {
  it("validates a draft and shows the result", async () => {
    mockFetch({ "POST /recipes/validate": { body: { ok: true, errors: [], warnings: [] } } });
    render(<MemoryRouter><RecipeEditor /></MemoryRouter>);
    await userEvent.click(screen.getByRole("button", { name: /validate/i }));
    await waitFor(() => expect(screen.getByText("Valid.")).toBeInTheDocument());
  });

  it("surfaces validation errors", async () => {
    mockFetch({ "POST /recipes/validate": { body: { ok: false, errors: ["w: duration_ms required"], warnings: [] } } });
    render(<MemoryRouter><RecipeEditor /></MemoryRouter>);
    await userEvent.click(screen.getByRole("button", { name: /validate/i }));
    await waitFor(() => expect(screen.getByText("w: duration_ms required")).toBeInTheDocument());
  });
});

describe("RecipeDetail", () => {
  it("loads versions and shows the latest", async () => {
    mockFetch({
      "GET /recipes/inv/versions": { body: [{ version: 1, content_hash: "sha256:a" }] },
      "GET /recipes/inv/versions/1": {
        body: { name: "Inverter", version: 1, content_hash: "sha256:a",
                steps: [{ step_id: "settle", step_type: "wait" }] },
      },
    });
    render(
      <MemoryRouter initialEntries={["/recipes/inv"]}>
        <AuthProvider>
          <Routes><Route path="/recipes/:id" element={<RecipeDetail />} /></Routes>
        </AuthProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("Inverter — v1")).toBeInTheDocument());
  });
});
