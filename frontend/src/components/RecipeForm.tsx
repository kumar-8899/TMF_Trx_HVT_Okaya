/** Shared recipe authoring/viewing surface — used editable by the editor and
 * read-only by the detail view. Phase-1 model: each test is a `parametric_test`
 * step = fixed fields + a flat list of {name, value, unit} parameter rows. */
import {
  Add, ArrowDownward, ArrowUpward, ContentCopy, DeleteOutline, NavigateBefore, NavigateNext, Search,
} from "@mui/icons-material";
import {
  Box, Button, Checkbox, Divider, FormControlLabel, IconButton, LinearProgress, MenuItem,
  Paper, Stack, Switch, Table, TableBody, TableCell, TableHead, TableRow, TextField,
  ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from "@mui/material";
import { useState } from "react";

import { MONO_STACK } from "../theme/theme";
import { Section, StatusDot } from "./ui";

export interface ParamRow { name: string; value?: number | string | boolean | null; unit?: string }
export interface Test {
  step_id: string;
  step_type: string;
  name?: string;
  test_group?: string;
  description?: string;
  enabled?: boolean;
  timeout_ms?: number;
  retry_count?: number;
  on_fail?: string;
  safety_critical?: boolean;
  params?: { parameters?: ParamRow[]; [k: string]: any };
}
export interface RecipeValue {
  recipe_id: string;
  name: string;
  model?: string;
  owner?: string;
  description?: string;
  steps: Test[];
}

const ON_FAIL = ["stop", "continue", "retry"];
export const PARAM_TYPE = "parametric_test";

/** Numeric-looking strings become numbers; blank clears the value. */
function coerce(v: string): number | string | undefined {
  const t = v.trim();
  if (t === "") return undefined;
  return /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : v;
}

type Status = "configured" | "partial" | "empty" | "error" | "disabled";
const DOT: Record<Status, "pass" | "running" | "idle" | "fail"> = {
  configured: "pass", partial: "running", empty: "idle", error: "fail", disabled: "idle",
};

function testStatus(t: Test, errorIds: Set<string>): Status {
  if (t.enabled === false) return "disabled";
  if (errorIds.has(t.step_id)) return "error";
  const rows = t.params?.parameters ?? [];
  if (t.step_type === PARAM_TYPE) {
    if (rows.length === 0) return "empty";
    return rows.every((r) => r.name?.trim()) ? "configured" : "partial";
  }
  return Object.keys(t.params ?? {}).length ? "configured" : "empty";
}

export function RecipeForm({
  value, onChange, readOnly = false, idLocked = false, errorIds = new Set<string>(),
}: {
  value: RecipeValue;
  onChange?: (v: RecipeValue) => void;
  readOnly?: boolean;
  idLocked?: boolean;
  errorIds?: Set<string>;
}) {
  const steps = value.steps;
  const [selected, setSelected] = useState(0);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "set" | "empty">("all");

  const patch = (v: Partial<RecipeValue>) => onChange?.({ ...value, ...v });
  const setSteps = (s: Test[]) => patch({ steps: s });
  const updateStep = (i: number, t: Test) => setSteps(steps.map((x, j) => (j === i ? t : x)));
  const setField = (i: number, k: keyof Test, v: any) => updateStep(i, { ...steps[i], [k]: v });
  const setRows = (i: number, r: ParamRow[]) =>
    updateStep(i, { ...steps[i], params: { ...steps[i].params, parameters: r } });

  const addTest = () => {
    const n = steps.length + 1;
    const t: Test = { step_id: `test_${n}`, step_type: PARAM_TYPE, name: `Test ${n}`, enabled: true, params: { parameters: [] } };
    setSteps([...steps, t]); setSelected(steps.length);
  };
  // unique step_id by incrementing the trailing number (test_3 -> test_4 -> …)
  const uniqueId = (base: string) => {
    const ids = new Set(steps.map((s) => s.step_id));
    const m = base.match(/^(.*?)(\d+)$/);
    const stem = m ? m[1] : `${base}_`;
    let n = m ? Number(m[2]) + 1 : 2;
    let id = `${stem}${n}`;
    while (ids.has(id)) { n++; id = `${stem}${n}`; }
    return id;
  };
  const duplicateTest = (i: number) => {
    const src = steps[i];
    const copy: Test = {
      ...src, step_id: uniqueId(src.step_id),
      name: src.name ? `${src.name} (copy)` : src.name,
      params: { ...src.params, parameters: (src.params?.parameters ?? []).map((p) => ({ ...p })) },
    };
    setSteps([...steps.slice(0, i + 1), copy, ...steps.slice(i + 1)]);
    setSelected(i + 1);
  };
  const removeTest = (i: number) => { setSteps(steps.filter((_, j) => j !== i)); setSelected((s) => Math.max(0, s > i ? s - 1 : s)); };
  const move = (i: number, d: number) => {
    const j = i + d; if (j < 0 || j >= steps.length) return;
    const c = [...steps]; [c[i], c[j]] = [c[j], c[i]]; setSteps(c); setSelected(j);
  };

  const has = (s: Test) => (s.params?.parameters?.length ?? 0) > 0;
  const setCount = steps.filter(has).length;
  const emptyCount = steps.length - setCount;
  const configured = steps.filter((s) => testStatus(s, errorIds) === "configured").length;
  const pct = steps.length ? Math.round((configured / steps.length) * 100) : 0;

  const railRows = steps.map((s, i) => ({ s, i })).filter(({ s }) => {
    if (filter === "set" && !has(s)) return false;
    if (filter === "empty" && has(s)) return false;
    const q = search.toLowerCase().trim();
    return !q || `${s.name ?? ""} ${s.step_id}`.toLowerCase().includes(q);
  });

  const cur = steps[selected];
  const curRows = cur?.params?.parameters ?? [];

  return (
    <Stack spacing={2}>
      <Section title="Recipe">
        <Stack spacing={2}>
          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
            <TextField label="Recipe ID" value={value.recipe_id} sx={{ width: 200 }} disabled={readOnly || idLocked}
              onChange={(e) => patch({ recipe_id: e.target.value })} inputProps={{ "aria-label": "recipe_id" }} />
            <TextField label="Name" value={value.name} sx={{ flex: 1, minWidth: 200 }} disabled={readOnly}
              onChange={(e) => patch({ name: e.target.value })} />
            <TextField label="Model" value={value.model ?? ""} sx={{ width: 180 }} disabled={readOnly}
              onChange={(e) => patch({ model: e.target.value })} helperText="DUT type name"
              inputProps={{ "aria-label": "model" }} />
            <TextField label="Owner" value={value.owner ?? ""} sx={{ width: 180 }} disabled
              helperText="Set to the creator" />
          </Stack>
          <TextField label="Description" value={value.description ?? ""} multiline minRows={1} disabled={readOnly}
            onChange={(e) => patch({ description: e.target.value })} />
          <Box>
            <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.5 }}>
              <Typography variant="caption" color="text.secondary">Configuration progress</Typography>
              <Typography variant="caption" color="text.secondary">{configured} of {steps.length} tests configured</Typography>
            </Stack>
            <LinearProgress variant="determinate" value={pct} color={pct === 100 ? "success" : "primary"} sx={{ height: 8, borderRadius: 4 }} />
          </Box>
        </Stack>
      </Section>

      <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems="stretch">
        {/* Left rail — sole navigation */}
        <Paper sx={{ width: { xs: "100%", md: 300 }, flexShrink: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <Box sx={{ bgcolor: "sectionHeader", color: "onNavy", px: 1.5, py: 1.25 }}>
            <Typography variant="subtitle2" sx={{ color: "onNavy" }}>Tests ({steps.length})</Typography>
          </Box>
          <Box sx={{ p: 1.5, pb: 1 }}>
            <TextField fullWidth size="small" placeholder="Search tests…" value={search}
              onChange={(e) => setSearch(e.target.value)}
              InputProps={{ startAdornment: <Search fontSize="small" sx={{ mr: 0.5, color: "text.secondary" }} /> }} />
            <ToggleButtonGroup exclusive size="small" value={filter} onChange={(_, v) => v && setFilter(v)} sx={{ mt: 1 }} fullWidth>
              <ToggleButton value="all">All {steps.length}</ToggleButton>
              <ToggleButton value="set">Set {setCount}</ToggleButton>
              <ToggleButton value="empty">Empty {emptyCount}</ToggleButton>
            </ToggleButtonGroup>
          </Box>
          <Divider />
          <Box sx={{ flex: 1, overflowY: "auto", maxHeight: { md: "52vh" } }}>
            {railRows.length === 0 ? (
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", p: 2, textAlign: "center" }}>
                {steps.length ? "No tests match." : "No tests yet."}
              </Typography>
            ) : railRows.map(({ s, i }) => {
              const st = testStatus(s, errorIds);
              const sel = i === selected;
              return (
                <Box key={i} onClick={() => setSelected(i)} sx={{
                  px: 1.5, py: 1, cursor: "pointer", display: "flex", alignItems: "center", gap: 1,
                  borderLeft: "3px solid", borderLeftColor: sel ? "primary.main" : "transparent",
                  bgcolor: sel ? (t) => (t.palette.mode === "dark" ? "rgba(30,158,87,0.12)" : "rgba(26,107,60,0.07)") : "transparent",
                  opacity: st === "disabled" ? 0.5 : 1,
                  "&:hover": { bgcolor: sel ? undefined : "action.hover" },
                  "&:hover .clone-btn": { opacity: 1 },
                }}>
                  <StatusDot kind={DOT[st]} />
                  <Box sx={{ minWidth: 0, flex: 1 }}>
                    <Typography variant="body2" noWrap sx={{ fontWeight: 600, textDecoration: st === "disabled" ? "line-through" : "none" }}>
                      {s.name || s.step_id}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block", fontFamily: MONO_STACK }}>
                      {s.step_id}
                    </Typography>
                  </Box>
                  {!readOnly && (
                    <Tooltip title="Duplicate test">
                      <IconButton className="clone-btn" size="small" sx={{ opacity: 0, transition: "opacity .15s" }}
                        onClick={(e) => { e.stopPropagation(); duplicateTest(i); }}>
                        <ContentCopy fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  )}
                </Box>
              );
            })}
          </Box>
          {!readOnly && (
            <>
              <Divider />
              <Box sx={{ p: 1.5 }}>
                <Button fullWidth variant="contained" startIcon={<Add />} onClick={addTest}>Add test</Button>
              </Box>
            </>
          )}
        </Paper>

        {/* Right pane — selected test */}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {!cur ? (
            <Section><Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: "center" }}>
              {readOnly ? "This recipe has no tests." : "Add a test on the left to begin."}
            </Typography></Section>
          ) : (
            <Stack spacing={2}>
              <Section
                title={cur.name || cur.step_id}
                subtitle={`Test ${selected + 1} of ${steps.length}`}
                actions={
                  <Stack direction="row" spacing={0.5} alignItems="center">
                    <FormControlLabel sx={{ mr: 0.5 }} control={
                      <Switch size="small" checked={cur.enabled !== false} disabled={readOnly}
                        onChange={(e) => setField(selected, "enabled", e.target.checked)} />
                    } label={<Typography variant="caption" sx={{ color: "onNavy" }}>Enabled</Typography>} />
                    {!readOnly && <>
                      <Tooltip title="Move up"><span><IconButton size="small" sx={{ color: "onNavy" }} disabled={selected === 0} onClick={() => move(selected, -1)}><ArrowUpward fontSize="small" /></IconButton></span></Tooltip>
                      <Tooltip title="Move down"><span><IconButton size="small" sx={{ color: "onNavy" }} disabled={selected >= steps.length - 1} onClick={() => move(selected, 1)}><ArrowDownward fontSize="small" /></IconButton></span></Tooltip>
                      <Tooltip title="Delete test"><IconButton size="small" sx={{ color: "onNavy" }} onClick={() => removeTest(selected)}><DeleteOutline fontSize="small" /></IconButton></Tooltip>
                    </>}
                  </Stack>
                }
              >
                {/* Fixed parameters */}
                <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                  <TextField label="Test ID" value={cur.step_id} sx={{ width: 180 }} disabled={readOnly}
                    onChange={(e) => setField(selected, "step_id", e.target.value)} />
                  <TextField label="Test name" value={cur.name ?? ""} sx={{ flex: 1, minWidth: 180 }} disabled={readOnly}
                    onChange={(e) => setField(selected, "name", e.target.value)} />
                  <TextField label="Test group" value={cur.test_group ?? ""} sx={{ width: 160 }} disabled={readOnly}
                    onChange={(e) => setField(selected, "test_group", e.target.value || undefined)}
                    inputProps={{ "aria-label": "test_group" }} />
                  <TextField label="Timeout (ms)" type="number" value={cur.timeout_ms ?? ""} sx={{ width: 130 }} disabled={readOnly}
                    onChange={(e) => setField(selected, "timeout_ms", e.target.value === "" ? undefined : Number(e.target.value))} />
                  <TextField label="Retry count" type="number" value={cur.retry_count ?? ""} sx={{ width: 130 }} disabled={readOnly}
                    onChange={(e) => setField(selected, "retry_count", e.target.value === "" ? undefined : Number(e.target.value))} />
                  <TextField select label="On fail" value={cur.on_fail ?? ""} sx={{ width: 140 }} disabled={readOnly}
                    onChange={(e) => setField(selected, "on_fail", e.target.value || undefined)}>
                    <MenuItem value=""><em>default</em></MenuItem>
                    {ON_FAIL.map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
                  </TextField>
                  <FormControlLabel control={
                    <Checkbox checked={Boolean(cur.safety_critical)} disabled={readOnly}
                      onChange={(e) => setField(selected, "safety_critical", e.target.checked)} />
                  } label="Safety critical" />
                </Stack>
              </Section>

              <Section title="Parameters" subtitle="Test-specific parameters" bodyPad={cur.step_type === PARAM_TYPE ? 0 : 2}>
                {cur.step_type !== PARAM_TYPE ? (
                  <Box component="pre" sx={{ fontFamily: MONO_STACK, fontSize: 12, m: 0, whiteSpace: "pre-wrap" }}>
                    {`(step type "${cur.step_type}" — edit in the phase-2 sequence editor)\n` + JSON.stringify(cur.params ?? {}, null, 2)}
                  </Box>
                ) : (
                  <>
                    <Table>
                      <TableHead>
                        <TableRow>
                          <TableCell>Parameter name</TableCell>
                          <TableCell>Value</TableCell>
                          <TableCell sx={{ width: 120 }}>Unit</TableCell>
                          {!readOnly && <TableCell sx={{ width: 48 }} />}
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {curRows.length === 0 ? (
                          <TableRow><TableCell colSpan={readOnly ? 3 : 4} sx={{ color: "text.secondary" }}>No parameters.</TableCell></TableRow>
                        ) : curRows.map((r, ri) => (
                          <TableRow key={ri}>
                            <TableCell>
                              <TextField fullWidth variant="standard" value={r.name} disabled={readOnly}
                                onChange={(e) => setRows(selected, curRows.map((x, j) => (j === ri ? { ...x, name: e.target.value } : x)))} />
                            </TableCell>
                            <TableCell>
                              <TextField fullWidth variant="standard" value={r.value ?? ""} disabled={readOnly}
                                onChange={(e) => setRows(selected, curRows.map((x, j) => (j === ri ? { ...x, value: coerce(e.target.value) } : x)))} />
                            </TableCell>
                            <TableCell>
                              <TextField fullWidth variant="standard" value={r.unit ?? ""} disabled={readOnly}
                                onChange={(e) => setRows(selected, curRows.map((x, j) => (j === ri ? { ...x, unit: e.target.value || undefined } : x)))} />
                            </TableCell>
                            {!readOnly && (
                              <TableCell>
                                <IconButton size="small" onClick={() => setRows(selected, curRows.filter((_, j) => j !== ri))}><DeleteOutline fontSize="small" /></IconButton>
                              </TableCell>
                            )}
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    {!readOnly && (
                      <Box sx={{ p: 1.5 }}>
                        <Button size="small" startIcon={<Add />} onClick={() => setRows(selected, [...curRows, { name: "" }])}>Add parameter</Button>
                      </Box>
                    )}
                  </>
                )}
              </Section>

              <Stack direction="row" justifyContent="space-between">
                <Button startIcon={<NavigateBefore />} disabled={selected === 0} onClick={() => setSelected((s) => s - 1)}>Previous</Button>
                <Button endIcon={<NavigateNext />} disabled={selected >= steps.length - 1} onClick={() => setSelected((s) => s + 1)}>Next</Button>
              </Stack>
            </Stack>
          )}
        </Box>
      </Stack>
    </Stack>
  );
}
