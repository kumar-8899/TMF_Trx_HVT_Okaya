import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ResultsTable } from "../../../components/testing/ResultsTable";
import {
  HIPOT_TESTS, HipotRecipeForm, buildSteps, emptyForm, modelIdError, parseRecipe,
  type FormValue,
} from "./HipotRecipeForm";

const withTests = (keys: string[], over: Partial<FormValue> = {}): FormValue => {
  const v = emptyForm();
  for (const k of keys) {
    v.selected.add(k);
    v.tests[k] = { voltageKv: 1.5, testTimeS: 3, maxCurrentMa: 5 };
  }
  return { ...v, ...over };
};

describe("modelIdError (mirrors the server's recipe_id rule)", () => {
  it.each(["1400", "TX-100", "tx_100-A", "a", "9".repeat(64)])("accepts %s", (id) => {
    expect(modelIdError(id)).toBeNull();
  });

  it.each(["", "   ", "../evil", "a/b", "a\\b", ".hidden", "has space", "x".repeat(65), "café",
    "trailing.", "a:b", "-lead", "_lead"])("rejects %j", (id) => {
    expect(modelIdError(id)).not.toBeNull();
  });

  it.each(["CON", "nul", "Com1", "LPT9"])("rejects the reserved name %s", (id) => {
    expect(modelIdError(id)).toMatch(/reserved/);
  });

  it("accepts names that merely START with a reserved word", () => {
    expect(modelIdError("CONSOLE")).toBeNull();
    expect(modelIdError("COM10")).toBeNull();
  });
});

describe("buildSteps / parseRecipe", () => {
  it("names each measurement after the human test label, not the snake_case key", () => {
    const steps = buildSteps(withTests(["pri_sec", "sec_fb"]));
    const names = steps.map((g) => g.params.steps[0].params.name);
    expect(names).toEqual(["Primary to Secondary", "Secondary to Feedback"]);
    expect(JSON.stringify(steps)).not.toMatch(/leakage_current/);
  });

  it("keeps the group ids (spec-lint / parseRecipe key off them) and the hipot params", () => {
    const [g] = buildSteps(withTests(["pri_core"]));
    expect(g.id).toBe("pri_core");
    const inner = g.params.steps[0];
    expect(inner.params).toMatchObject({
      route: ["hipot_route_pri_core"], voltage: 1500, test_time: 3, max_current_ma: 5,
    });
  });

  it("round-trips Model ID, stop-on-fail and the selected tests", () => {
    const form = withTests(["pri_sec", "fb_core"], { modelId: "TX-100", stopOnFail: true });
    const parsed = parseRecipe({
      recipe_id: form.modelId, name: "TX", model: "TX", stop_on_fail: form.stopOnFail,
      steps: buildSteps(form),
    });
    expect(parsed.modelId).toBe("TX-100");
    expect(parsed.stopOnFail).toBe(true);
    expect([...parsed.selected].sort()).toEqual(["fb_core", "pri_sec"]);
    expect(parsed.tests.pri_sec).toEqual({ voltageKv: 1.5, testTimeS: 3, maxCurrentMa: 5 });
  });

  it("stop-on-fail is strictly `true`, defaulting OFF so existing recipes parse unchanged", () => {
    expect(parseRecipe({ steps: [] }).stopOnFail).toBe(false);
    for (const bogus of ["true", 1, "yes", null]) {
      expect(parseRecipe({ stop_on_fail: bogus, steps: [] }).stopOnFail).toBe(false);
    }
    expect(parseRecipe({ stop_on_fail: true, steps: [] }).stopOnFail).toBe(true);
  });

  it("still reads a recipe saved with the OLD snake_case measurement names", () => {
    const old = { recipe_id: "inv_1", steps: [{ type: "group", id: "pri_sec", params: { steps: [
      { type: "hipot_acw", id: "pri_sec_hipot", params: {
        route: ["hipot_route_pri_sec"], voltage: 2000, test_time: 2, max_current_ma: 4,
        name: "pri_sec_leakage_current" } }] } }] };
    const v = parseRecipe(old);
    expect(v.selected.has("pri_sec")).toBe(true);
    expect(v.tests.pri_sec.voltageKv).toBe(2);
    // re-saving it from the form upgrades the name to the label
    expect(buildSteps(v)[0].params.steps[0].params.name).toBe("Primary to Secondary");
  });
});

describe("HipotRecipeForm — Model ID", () => {
  it("is an editable, required field when creating a recipe", () => {
    render(<HipotRecipeForm value={emptyForm()} onChange={() => {}} />);
    const id = screen.getByLabelText("Model ID");
    expect(id).toBeEnabled();
    expect(id).toBeRequired();
    expect(screen.getByText(/Cannot be changed after the recipe is created/)).toBeInTheDocument();
  });

  it("is locked once the recipe exists", () => {
    render(<HipotRecipeForm value={{ ...emptyForm(), modelId: "1400" }} onChange={() => {}} idLocked />);
    const id = screen.getByLabelText("Model ID");
    expect(id).toBeDisabled();
    expect(id).toHaveValue("1400");
    expect(screen.getByText(/Fixed when the recipe was created/)).toBeInTheDocument();
  });

  it("is locked in the read-only view", () => {
    render(<HipotRecipeForm value={{ ...emptyForm(), modelId: "1400" }} readOnly />);
    expect(screen.getByLabelText("Model ID")).toBeDisabled();
  });

  it("trims stray edge whitespace but never silently rewrites the middle of an ID", () => {
    const onChange = vi.fn();
    render(<HipotRecipeForm value={emptyForm()} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Model ID"), { target: { value: "  TX-100 " } });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ modelId: "TX-100" }));
    // an inner space is kept as typed (and flagged below) rather than quietly deleted
    fireEvent.change(screen.getByLabelText("Model ID"), { target: { value: "bad id" } });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ modelId: "bad id" }));
  });

  it("reports the reason for an invalid ID", () => {
    render(<HipotRecipeForm value={{ ...emptyForm(), modelId: "bad id" }} onChange={() => {}} />);
    expect(screen.getByText(/no spaces or symbols/)).toBeInTheDocument();
    expect(screen.getByLabelText("Model ID")).toHaveAttribute("aria-invalid", "true");
  });
});

describe("HipotRecipeForm — stop on first failure", () => {
  it("reflects the value and explains each state", () => {
    const { rerender } = render(<HipotRecipeForm value={emptyForm()} onChange={() => {}} />);
    expect(screen.getByLabelText("Stop on first failure")).not.toBeChecked();
    expect(screen.getByText(/OFF — every selected test runs/)).toBeInTheDocument();

    rerender(<HipotRecipeForm value={{ ...emptyForm(), stopOnFail: true }} onChange={() => {}} />);
    expect(screen.getByLabelText("Stop on first failure")).toBeChecked();
    expect(screen.getByText(/ON — the run stops at the first failed test/)).toBeInTheDocument();
  });

  it("toggles via onChange", () => {
    const onChange = vi.fn();
    render(<HipotRecipeForm value={emptyForm()} onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("Stop on first failure"));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ stopOnFail: true }));
  });

  it("cannot be toggled in the read-only view", () => {
    render(<HipotRecipeForm value={{ ...emptyForm(), stopOnFail: true }} readOnly />);
    expect(screen.getByLabelText("Stop on first failure")).toBeDisabled();
  });
});

describe("Results table shows exactly the labels the recipe emits", () => {
  it("renders every test point's label unchanged, including a FAIL/ERROR row", () => {
    const names = buildSteps(withTests(HIPOT_TESTS.map((t) => t.key)))
      .map((g) => g.params.steps[0].params.name as string);
    const rows = names.map((n, i) => ({
      serial_no: i + 1, test_name: n, expected: "≤ 5", measured: i === 1 ? "ERROR" : 1.2,
      result: i === 1 ? "FAIL" : "PASS",
    }));
    render(<ResultsTable rows={rows} />);
    for (const t of HIPOT_TESTS) expect(screen.getByText(t.label)).toBeInTheDocument();
    expect(screen.queryByText(/leakage/i)).not.toBeInTheDocument();
    expect(screen.getByText("ERROR")).toBeInTheDocument();
    expect(screen.getByText("FAIL")).toBeInTheDocument();
  });
});
