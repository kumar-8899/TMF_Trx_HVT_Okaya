import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockFetch } from "../test/fetchMock";
import { RecipeForm, type RecipeValue } from "./RecipeForm";

// Regression: the "Inner steps" JSON box of a group step kept the text of the FIRST step when another
// group step was selected (every group has the same param name, and the box only reloaded on a name
// change). Editing it then wrote the wrong inner steps into the selected group.
const GROUP_TYPE = {
  type_id: "group", display_name: "Group", composite: true,
  schema: { properties: { steps: { type: "array", description: "Inner steps" } }, required: ["steps"] },
};

const recipe: RecipeValue = {
  recipe_id: "demo", name: "Demo",
  steps: [
    { id: "g1", type: "group", name: "First", params: { steps: [{ id: "only_in_first", type: "wait" }] } },
    { id: "g2", type: "group", name: "Second", params: { steps: [{ id: "only_in_second", type: "wait" }] } },
  ],
};

describe("RecipeForm group steps", () => {
  it("shows the inner steps of the selected group, not of the first one", async () => {
    mockFetch({ "GET /recipes/step-types": { body: [GROUP_TYPE] } });
    render(<RecipeForm value={recipe} onChange={() => {}} />);

    await waitFor(() => expect(screen.getByDisplayValue(/only_in_first/)).toBeInTheDocument());
    await userEvent.click(screen.getAllByText("Second")[0]);

    await waitFor(() => expect(screen.getByDisplayValue(/only_in_second/)).toBeInTheDocument());
    expect(screen.queryByDisplayValue(/only_in_first/)).not.toBeInTheDocument();
  });
});
