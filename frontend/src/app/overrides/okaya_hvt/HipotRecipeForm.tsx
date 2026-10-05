/** Shared hipot AC-withstand recipe form — used by both the editor (/recipes/new · /edit) and
 * the read-only detail view (/recipes/:id) so authoring and viewing look identical (app-owned
 * override, TEMPLATE.md §1.3). Holds the domain model + the recipe<->form mapping so the two
 * screens stay in sync. Styled with the framework theme (Section, MUI).
 *
 * Replaces the earlier Variac-based TransformerRecipeForm (2026-09): that form built
 * `variac_regulate` steps and read `selec_mfm384`-backed signals (`input_voltage`,
 * `no_load_current`, `winding_voltage1`, `line_frequency`) — none of which exist on this bench
 * (no Variac, no NI, and the `selec_mfm384` meter was removed). This bench's only authored test
 * is the six-point hipot AC-withstand sequence (`hipot_acw` step type, `app/okaya_hvt/specs/
 * hipot_acw.md`), routed through the Waveshare relay card to the shared UT5320R+ tester. */
import {
  Checkbox, FormControlLabel, Grid, InputAdornment, Paper, Stack, Switch, TextField, Typography,
} from "@mui/material";

import { Section } from "../../../components/ui";

/* ---------------------------------------------------------------- test model */
// The six hipot test points (INSTRUMENT_DRIVERS.md "The hipot tester") — one relay route each,
// all sharing the one `hipot_acw` step type and the one `hipot` action (maps/st1.json).
//
// UNCONFIRMED: the route channel numbers (Ch0-Ch5) are still not confirmed against the real
// board, though relay1 now carries only these six routes (the digital I/O and dimmer_output/
// w1_meas/w2_meas/w3_meas coil writes that used to share it were removed 2026-09) — see the
// `//relay_modules` note in maps/st1.json. Resolve before running any of these against real HV.
export interface HipotTestDef { key: string; label: string; routeSignal: string }

export const HIPOT_TESTS: HipotTestDef[] = [
  { key: "pri_sec", label: "Primary to Secondary", routeSignal: "hipot_route_pri_sec" },
  { key: "pri_core", label: "Primary to Core", routeSignal: "hipot_route_pri_core" },
  { key: "sec_core", label: "Secondary to Core", routeSignal: "hipot_route_sec_core" },
  { key: "fb_core", label: "Feedback to Core", routeSignal: "hipot_route_fb_core" },
  { key: "pri_fb", label: "Primary to Feedback", routeSignal: "hipot_route_pri_fb" },
  { key: "sec_fb", label: "Secondary to Feedback", routeSignal: "hipot_route_sec_fb" },
];

// The three parameters the schema (okaya_hvt_steps/hipot_acw/schema.json) actually takes per
// test point. voltageKv is a UI-only unit: the step's `voltage` param is volts (device range
// 50-5000 V), so the form multiplies by 1000 going out and divides coming back in.
export interface HipotParams {
  voltageKv: number;    // ACW voltage — UI shows kV, step param `voltage` is V
  testTimeS: number;    // Test time (s) — step param `test_time`
  maxCurrentMa: number; // Max current (mA) — step param `max_current_ma`
}

export interface FormValue {
  modelId: string;      // the recipe's immutable ID (becomes `recipe_id`, a folder name on disk)
  model: string;        // display name — editable any time
  description: string;
  stopOnFail: boolean;  // recipe-level `stop_on_fail`: stop the run at the first failed test
  selected: Set<string>;
  tests: Record<string, HipotParams>;
}

// The Model ID is typed by the user and used verbatim as the recipe_id, which the backend stores
// as a FOLDER NAME — so it is restricted to the same set the server enforces (RecipeStore
// create: modules/recipe/variants/filesystem.py `_check_recipe_id`). The server is the real
// boundary; this just gives the operator the reason up front instead of a 422 after Save.
const MODEL_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
const RESERVED_ID_RE = /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$/i;
export function modelIdError(id: string): string | null {
  const s = id.trim();
  if (!s) return "Enter a Model ID.";
  if (!MODEL_ID_RE.test(s)) {
    return "Use 1-64 letters, digits, '-' or '_' (starting with a letter or digit); no spaces or symbols.";
  }
  if (RESERVED_ID_RE.test(s)) return `"${s}" is a reserved name — choose another ID.`;
  return null;
}

// Zero, not a plausible-looking guess: the real per-test-point ACW voltage/time/current-limit
// numbers are the product spec's, entered by the engineer — never invented here (mirrors the
// step type's own schema, which has no `default` on these three for the same reason).
export const zeroParams = (): HipotParams => ({ voltageKv: 0, testTimeS: 0, maxCurrentMa: 0 });

export const emptyForm = (): FormValue => ({
  // stopOnFail defaults OFF: that is what every recipe did before the toggle existed (the
  // controller runs every selected test and reports each), so existing recipes parse unchanged.
  modelId: "", model: "", description: "", stopOnFail: false, selected: new Set(),
  tests: Object.fromEntries(HIPOT_TESTS.map((t) => [t.key, zeroParams()])),
});

export const slug = (s: string) => s.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");

/* ---------------------------------------------------------------- form <-> recipe steps */
// One recipe GROUP per selected test point (id = the test key, e.g. "pri_sec"), each wrapping
// exactly one hipot_acw step — matches the per-group spec-lint convention (docs/TEST_SPECS.md):
// a recipe group named "pri_sec" gets its own `specs/pri_sec.md` once authored. The measurement
// name is the test point's human LABEL ("Primary to Secondary"), fixed by this function and not
// user-editable: it is exactly what the Results table / reports show as the test name. (It was
// `<key>_leakage_current`, which rendered as "pri_sec_leakage_current". If a per-group spec is
// authored later, its Output table must list the label — spec-lint matches names literally.)
export function buildSteps(v: FormValue): any[] {
  const steps: any[] = [];
  for (const t of HIPOT_TESTS) {
    if (!v.selected.has(t.key)) continue;
    const p = v.tests[t.key];
    steps.push({
      type: "group", id: t.key,
      params: {
        name: t.label,
        steps: [
          {
            type: "hipot_acw", id: `${t.key}_hipot`,
            params: {
              route: [t.routeSignal],
              voltage: p.voltageKv * 1000,
              test_time: p.testTimeS,
              max_current_ma: p.maxCurrentMa,
              name: t.label,
            },
          },
        ],
      },
    });
  }
  return steps;
}

export function parseRecipe(recipe: any): FormValue {
  const v = emptyForm();
  v.modelId = recipe?.recipe_id || "";
  v.model = recipe?.model || recipe?.name || "";
  v.description = recipe?.description || "";
  v.stopOnFail = recipe?.stop_on_fail === true;   // strictly `true` — mirrors the controller
  for (const g of recipe?.steps ?? []) {
    const t = HIPOT_TESTS.find((x) => x.key === g.id);
    if (!t) continue;
    const inner = (g.params?.steps ?? [])[0];
    const p = inner?.params ?? {};
    v.selected.add(t.key);
    v.tests[t.key] = {
      voltageKv: (Number(p.voltage) || 0) / 1000,
      testTimeS: Number(p.test_time) || 0,
      maxCurrentMa: Number(p.max_current_ma) || 0,
    };
  }
  return v;
}

/* ---------------------------------------------------------------- field */
function NumField({
  label, value, unit, onChange, disabled,
}: { label: string; value: number; unit?: string; onChange: (v: number) => void; disabled?: boolean }) {
  return (
    <TextField
      label={label} type="number" size="small" fullWidth disabled={disabled}
      value={Number.isFinite(value) ? value : 0}
      onChange={(e) => { const n = parseFloat(e.target.value); onChange(Number.isFinite(n) ? Math.max(0, n) : 0); }}
      InputProps={unit ? { endAdornment: <InputAdornment position="end">{unit}</InputAdornment> } : undefined}
      inputProps={{ step: "any", min: 0 }}
    />
  );
}

/* ---------------------------------------------------------------- the form */
export function HipotRecipeForm({
  value, onChange, readOnly = false, idLocked = false,
}: {
  value: FormValue; onChange?: (v: FormValue) => void; readOnly?: boolean;
  /** The Model ID is fixed once the recipe exists (editing a saved recipe / the read-only view). */
  idLocked?: boolean;
}) {
  const idEditable = !readOnly && !idLocked;
  const idErr = idEditable && value.modelId ? modelIdError(value.modelId) : null;
  const patch = (p: Partial<FormValue>) => onChange?.({ ...value, ...p });
  const toggle = (key: string) => {
    const n = new Set(value.selected); n.has(key) ? n.delete(key) : n.add(key); patch({ selected: n });
  };
  const setParams = (key: string, p: Partial<HipotParams>) =>
    patch({ tests: { ...value.tests, [key]: { ...value.tests[key], ...p } } });

  // In read-only mode, only show the tests that are actually part of the recipe.
  const listedTests = readOnly ? HIPOT_TESTS.filter((t) => value.selected.has(t.key)) : HIPOT_TESTS;
  const anySelected = value.selected.size > 0;

  const testPanel = (t: HipotTestDef) => {
    const p = value.tests[t.key];
    return (
      <Grid item xs={12} md={6} key={t.key}>
        <Section title={t.label}>
          <Grid container spacing={2}>
            <Grid item xs={12}>
              <NumField label="ACW Voltage" unit="kV" value={p.voltageKv} disabled={readOnly}
                onChange={(x) => setParams(t.key, { voltageKv: x })} />
            </Grid>
            <Grid item xs={12}>
              <NumField label="Test Time" unit="sec" value={p.testTimeS} disabled={readOnly}
                onChange={(x) => setParams(t.key, { testTimeS: x })} />
            </Grid>
            <Grid item xs={12}>
              <NumField label="Max Current" unit="mA" value={p.maxCurrentMa} disabled={readOnly}
                onChange={(x) => setParams(t.key, { maxCurrentMa: x })} />
            </Grid>
          </Grid>
        </Section>
      </Grid>
    );
  };

  return (
    <Grid container spacing={2}>
      <Grid item xs={12} md={4}>
        <Stack spacing={2}>
          <Section title="Recipe">
            <Stack spacing={2}>
              <TextField label="Model ID" size="small" fullWidth required={idEditable}
                value={value.modelId} disabled={!idEditable} error={!!idErr}
                onChange={(e) => patch({ modelId: e.target.value.trim() })} placeholder="e.g. 1400"
                inputProps={{ maxLength: 64, "aria-label": "Model ID" }}
                helperText={idEditable
                  ? (idErr ?? "Letters, digits, - and _. Cannot be changed after the recipe is created.")
                  : "Fixed when the recipe was created."} />
              <TextField label="Model name" size="small" fullWidth value={value.model} disabled={readOnly}
                onChange={(e) => patch({ model: e.target.value })} placeholder="e.g. TX-100" />
              <TextField label="Description" size="small" fullWidth multiline minRows={2} disabled={readOnly}
                value={value.description} onChange={(e) => patch({ description: e.target.value })} />
              <FormControlLabel
                control={<Switch checked={value.stopOnFail} disabled={readOnly}
                  onChange={(e) => patch({ stopOnFail: e.target.checked })}
                  inputProps={{ "aria-label": "Stop on first failure" }} />}
                label={
                  <Stack>
                    <Typography variant="body2">Stop on first failure</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {value.stopOnFail
                        ? "ON — the run stops at the first failed test; later tests are not run."
                        : "OFF — every selected test runs, and every result is reported."}
                    </Typography>
                  </Stack>
                } />
            </Stack>
          </Section>

          <Section title={readOnly ? "Tests in this recipe" : "Select required tests"}>
            {listedTests.length === 0 ? (
              <Typography variant="body2" color="text.secondary">No tests.</Typography>
            ) : (
              <Stack spacing={0.5}>
                {listedTests.map((t) => (
                  <FormControlLabel key={t.key}
                    control={<Checkbox checked={value.selected.has(t.key)} disabled={readOnly}
                      onChange={() => toggle(t.key)} />}
                    label={<Typography variant="body2">{t.label}</Typography>} />
                ))}
              </Stack>
            )}
          </Section>
        </Stack>
      </Grid>

      <Grid item xs={12} md={8}>
        <Grid container spacing={2}>
          {listedTests.filter((t) => value.selected.has(t.key)).map(testPanel)}

          {!anySelected && (
            <Grid item xs={12}>
              <Paper sx={{ p: 4, textAlign: "center" }}>
                <Typography color="text.secondary">
                  {readOnly ? "This recipe has no configured tests."
                    : "Select one or more tests on the left to configure their parameters."}
                </Typography>
              </Paper>
            </Grid>
          )}
        </Grid>
      </Grid>
    </Grid>
  );
}
