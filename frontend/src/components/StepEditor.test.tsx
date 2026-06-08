import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { mockFetch } from "../test/fetchMock";
import { SchemaForm, StepList } from "./StepEditor";

describe("SchemaForm", () => {
  it("renders fields from a resolved schema", () => {
    const schema = {
      properties: {
        duration_ms: { type: "integer" },
        level: { enum: ["info", "warning"] },
      },
      required: ["duration_ms"],
    };
    render(<SchemaForm schema={schema} value={{}} onChange={() => {}} types={[]} />);
    expect(screen.getByLabelText("duration_ms *")).toBeInTheDocument();
    expect(screen.getByText("level")).toBeInTheDocument(); // enum placeholder
  });

  it("emits param changes", async () => {
    const onChange = vi.fn();
    render(<SchemaForm schema={{ properties: { variable: { type: "string" } } }}
      value={{}} onChange={onChange} types={[]} />);
    await userEvent.type(screen.getByLabelText("variable"), "vbus_main");
    expect(onChange).toHaveBeenCalled();
  });
});

describe("StepList", () => {
  it("removes a step", async () => {
    mockFetch({ "GET /recipes/step-types/wait/schema": { body: { properties: {} } } });
    const onChange = vi.fn();
    const steps = [{ step_id: "w", step_type: "wait", params: {} }];
    render(<StepList steps={steps} onChange={onChange} types={[]} />);
    await waitFor(() => expect(screen.getByDisplayValue("w")).toBeInTheDocument());
    await userEvent.click(screen.getByLabelText("remove"));
    expect(onChange).toHaveBeenCalledWith([]);
  });
});
