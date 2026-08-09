/** Recipe authoring/viewing surface — controller-native recipes (recipe-unify P4).
 *
 * A recipe is an ordered list of steps `{ id, type, params }`; the step types + their
 * parameter JSON schemas come from the controller catalog (`GET /step-types`: the 8 core
 * types + the app's step_type_packages). The right-pane param form is rendered from the
 * selected step type's schema. Same two-pane look as before. Composite params (a nested
 * `steps` list) and other array/object params are edited as JSON. */
import {
  Add, ArrowDownward, ArrowUpward, ContentCopy, DeleteOutline, NavigateBefore, NavigateNext, Search,
} from "@mui/icons-material";
import {
  Box, Button, Checkbox, Divider, FormControlLabel, IconButton, LinearProgress, MenuItem,
  Paper, Stack, Switch, TextField, Tooltip, Typography,
} from "@mui/material";
import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import { MONO_STACK } from "../theme/theme";
import { Section, StatusDot } from "./ui";

export interface Step {
  id: string;
  type: string;
  name?: string;
  test_group?: string;
  enabled?: boolean;
  timeout_ms?: number;
  retry_count?: number;
  on_fail?: string;
  safety_critical?: boolean;
  params?: Record<string, any>;
}
export interface RecipeValue {
  recipe_id: string;
  name: string;
  model?: string;
  owner?: string;
  description?: string;
  steps: Step[];
}

interface StepType {
  type_id: string;
  display_name: string;
  composite: boolean;
  kind?: string;
  required_signals?: string[];
  required_actions?: string[];
  schema?: { properties?: Record<string, any>; required?: string[] } | null;
}

const ON_FAIL = ["stop", "continue", "retry"];

type Status = "configured" | "empty" | "error" | "disabled";
const DOT: Record<Status, "pass" | "idle" | "fail"> = {
  configured: "pass", empty: "idle", error: "fail", disabled: "idle",
};

function requiredOf(t: StepType | undefined): string[] {
  return t?.schema?.required ?? [];
}
function stepStatus(s: Step, type: StepType | undefined, errorIds: Set<string>): Status {
  if (s.enabled === false) return "disabled";
  if (errorIds.has(s.id)) return "error";
  const req = requiredOf(type);
  const p = s.params ?? {};
  return req.every((k) => p[k] !== undefined && p[k] !== "") ? "configured" : (req.length ? "empty" : "configured");
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
  const [types, setTypes] = useState<StepType[]>([]);

  useEffect(() => { api.get("/recipes/step-types").then(setTypes).catch(() => setTypes([])); }, []);
  const typeById = useMemo(() => Object.fromEntries(types.map((t) => [t.type_id, t])), [types]);
  const defaultType = typeById["measure_and_compare"] ? "measure_and_compare"
    : (types.find((t) => !t.composite)?.type_id || types[0]?.type_id || "measure_and_compare");

  const patch = (v: Partial<RecipeValue>) => onChange?.({ ...value, ...v });
  const setSteps = (s: Step[]) => patch({ steps: s });
  const updateStep = (i: number, s: Step) => setSteps(steps.map((x, j) => (j === i ? s : x)));
  const setField = (i: number, k: keyof Step, v: any) => updateStep(i, { ...steps[i], [k]: v });
  const setParam = (i: number, key: string, v: any) => {
    const p = { ...(steps[i].params ?? {}) };
    if (v === undefined || v === "") delete p[key]; else p[key] = v;
    updateStep(i, { ...steps[i], params: p });
  };

  const uniqueId = (base: string) => {
    const ids = new Set(steps.map((s) => s.id));
    const m = base.match(/^(.*?)(\d+)$/);
    const stem = m ? m[1] : `${base}_`;
    let n = m ? Number(m[2]) + 1 : 2;
    let id = `${stem}${n}`;
    while (ids.has(id)) { n++; id = `${stem}${n}`; }
    return id;
  };
  const addStep = () => {
    const n = steps.length + 1;
    setSteps([...steps, { id: `step_${n}`, type: defaultType, name: `Step ${n}`, enabled: true, params: {} }]);
    setSelected(steps.length);
  };
  const duplicateStep = (i: number) => {
    const src = steps[i];
    const copy: Step = { ...src, id: uniqueId(src.id), name: src.name ? `${src.name} (copy)` : src.name,
      params: { ...(src.params ?? {}) } };
    setSteps([...steps.slice(0, i + 1), copy, ...steps.slice(i + 1)]); setSelected(i + 1);
  };
  const removeStep = (i: number) => { setSteps(steps.filter((_, j) => j !== i)); setSelected((s) => Math.max(0, s > i ? s - 1 : s)); };
  const move = (i: number, d: number) => {
    const j = i + d; if (j < 0 || j >= steps.length) return;
    const c = [...steps]; [c[i], c[j]] = [c[j], c[i]]; setSteps(c); setSelected(j);
  };

  const configured = steps.filter((s) => stepStatus(s, typeById[s.type], errorIds) === "configured").length;
  const pct = steps.length ? Math.round((configured / steps.length) * 100) : 0;

  const railRows = steps.map((s, i) => ({ s, i })).filter(({ s }) => {
    const q = search.toLowerCase().trim();
    return !q || `${s.name ?? ""} ${s.id} ${s.type}`.toLowerCase().includes(q);
  });

  const cur = steps[selected];
  const curType = cur ? typeById[cur.type] : undefined;

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
            <TextField label="Owner" value={value.owner ?? ""} sx={{ width: 180 }} disabled helperText="Set to the creator" />
          </Stack>
          <TextField label="Description" value={value.description ?? ""} multiline minRows={1} disabled={readOnly}
            onChange={(e) => patch({ description: e.target.value })} />
          <Box>
            <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.5 }}>
              <Typography variant="caption" color="text.secondary">Configuration progress</Typography>
              <Typography variant="caption" color="text.secondary">{configured} of {steps.length} steps configured</Typography>
            </Stack>
            <LinearProgress variant="determinate" value={pct} color={pct === 100 ? "success" : "primary"} sx={{ height: 8, borderRadius: 4 }} />
          </Box>
        </Stack>
      </Section>

      <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems="stretch">
        {/* Left rail */}
        <Paper sx={{ width: { xs: "100%", md: 300 }, flexShrink: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <Box sx={{ bgcolor: "sectionHeader", color: "onNavy", px: 1.5, py: 1.25 }}>
            <Typography variant="subtitle2" sx={{ color: "onNavy" }}>Steps ({steps.length})</Typography>
          </Box>
          <Box sx={{ p: 1.5, pb: 1 }}>
            <TextField fullWidth size="small" placeholder="Search steps…" value={search}
              onChange={(e) => setSearch(e.target.value)}
              InputProps={{ startAdornment: <Search fontSize="small" sx={{ mr: 0.5, color: "text.secondary" }} /> }} />
          </Box>
          <Divider />
          <Box sx={{ flex: 1, overflowY: "auto", maxHeight: { md: "52vh" } }}>
            {railRows.length === 0 ? (
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", p: 2, textAlign: "center" }}>
                {steps.length ? "No steps match." : "No steps yet."}
              </Typography>
            ) : railRows.map(({ s, i }) => {
              const st = stepStatus(s, typeById[s.type], errorIds);
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
                      {s.name || s.id}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block", fontFamily: MONO_STACK }}>
                      {s.id} · {s.type}
                    </Typography>
                  </Box>
                  {!readOnly && (
                    <Tooltip title="Duplicate step">
                      <IconButton className="clone-btn" size="small" sx={{ opacity: 0, transition: "opacity .15s" }}
                        onClick={(e) => { e.stopPropagation(); duplicateStep(i); }}>
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
              <Box sx={{ p: 1.5 }}><Button fullWidth variant="contained" startIcon={<Add />} onClick={addStep}>Add step</Button></Box>
            </>
          )}
        </Paper>

        {/* Right pane */}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {!cur ? (
            <Section><Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: "center" }}>
              {readOnly ? "This recipe has no steps." : "Add a step on the left to begin."}
            </Typography></Section>
          ) : (
            <Stack spacing={2}>
              <Section
                title={cur.name || cur.id}
                subtitle={`Step ${selected + 1} of ${steps.length}`}
                actions={
                  <Stack direction="row" spacing={0.5} alignItems="center">
                    <FormControlLabel sx={{ mr: 0.5 }} control={
                      <Switch size="small" checked={cur.enabled !== false} disabled={readOnly}
                        onChange={(e) => setField(selected, "enabled", e.target.checked)} />
                    } label={<Typography variant="caption" sx={{ color: "onNavy" }}>Enabled</Typography>} />
                    {!readOnly && <>
                      <Tooltip title="Move up"><span><IconButton size="small" sx={{ color: "onNavy" }} disabled={selected === 0} onClick={() => move(selected, -1)}><ArrowUpward fontSize="small" /></IconButton></span></Tooltip>
                      <Tooltip title="Move down"><span><IconButton size="small" sx={{ color: "onNavy" }} disabled={selected >= steps.length - 1} onClick={() => move(selected, 1)}><ArrowDownward fontSize="small" /></IconButton></span></Tooltip>
                      <Tooltip title="Delete step"><IconButton size="small" sx={{ color: "onNavy" }} onClick={() => removeStep(selected)}><DeleteOutline fontSize="small" /></IconButton></Tooltip>
                    </>}
                  </Stack>
                }
              >
                <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                  <TextField label="Step ID" value={cur.id} sx={{ width: 180 }} disabled={readOnly}
                    onChange={(e) => setField(selected, "id", e.target.value)} />
                  <TextField label="Step name" value={cur.name ?? ""} sx={{ flex: 1, minWidth: 160 }} disabled={readOnly}
                    onChange={(e) => setField(selected, "name", e.target.value)} />
                  <TextField select label="Step type" value={cur.type} sx={{ width: 220 }} disabled={readOnly}
                    onChange={(e) => setField(selected, "type", e.target.value)} inputProps={{ "aria-label": "step_type" }}>
                    {types.map((t) => <MenuItem key={t.type_id} value={t.type_id}>{t.display_name}{t.composite ? " (group)" : ""}</MenuItem>)}
                    {!typeById[cur.type] && <MenuItem value={cur.type}>{cur.type}</MenuItem>}
                  </TextField>
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

              <Section title="Parameters" subtitle={curType?.display_name ? `${curType.display_name} — from its schema` : cur.type}>
                <ParamsForm type={curType} params={cur.params ?? {}} readOnly={readOnly}
                  onSet={(k, v) => setParam(selected, k, v)} />
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

/** Renders one form field per schema property; scalars get native inputs, arrays/objects
 * (points, values, step_map, composite `steps`, condition/until) are edited as JSON. */
function ParamsForm({ type, params, readOnly, onSet }: {
  type: StepType | undefined; params: Record<string, any>; readOnly: boolean;
  onSet: (key: string, value: any) => void;
}) {
  const props = type?.schema?.properties;
  const required = new Set(type?.schema?.required ?? []);
  if (!props || Object.keys(props).length === 0) {
    return <Typography variant="body2" color="text.secondary">This step type has no parameters.</Typography>;
  }
  const scalars = Object.entries(props).filter(([, s]: any) => ["number", "integer", "string", "boolean"].includes(s.type) || s.enum);
  const complex = Object.entries(props).filter(([, s]: any) => !(["number", "integer", "string", "boolean"].includes(s.type) || s.enum));
  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="flex-start">
        {scalars.map(([key, spec]: any) => (
          <Field key={key} name={key} spec={spec} required={required.has(key)} readOnly={readOnly}
            value={params[key]} onSet={(v: any) => onSet(key, v)} />
        ))}
      </Stack>
      {complex.map(([key, spec]: any) => (
        <JsonField key={key} name={key} spec={spec} required={required.has(key)} readOnly={readOnly}
          value={params[key]} onSet={(v: any) => onSet(key, v)} />
      ))}
    </Stack>
  );
}

function label(name: string, spec: any, required: boolean) {
  return (spec.title || name) + (required ? " *" : "");
}

function Field({ name, spec, required, readOnly, value, onSet }: any) {
  const help = spec.description as string | undefined;
  if (spec.type === "boolean") {
    return <FormControlLabel control={<Switch checked={Boolean(value ?? spec.default)} disabled={readOnly}
      onChange={(e) => onSet(e.target.checked)} />} label={label(name, spec, required)} />;
  }
  if (spec.enum) {
    return <TextField select label={label(name, spec, required)} value={value ?? ""} sx={{ width: 200 }} disabled={readOnly}
      helperText={help} onChange={(e) => onSet(e.target.value || undefined)}>
      <MenuItem value=""><em>—</em></MenuItem>
      {spec.enum.map((o: any) => <MenuItem key={String(o)} value={o}>{String(o)}</MenuItem>)}
    </TextField>;
  }
  const num = spec.type === "number" || spec.type === "integer";
  return <TextField label={label(name, spec, required)} type={num ? "number" : "text"} value={value ?? ""} sx={{ width: 200 }}
    disabled={readOnly} helperText={help}
    onChange={(e) => onSet(e.target.value === "" ? undefined : (num ? Number(e.target.value) : e.target.value))}
    inputProps={{ "aria-label": name }} />;
}

function JsonField({ name, spec, required, readOnly, value, onSet }: any) {
  const [text, setText] = useState(value === undefined ? "" : JSON.stringify(value, null, 1));
  const [bad, setBad] = useState(false);
  useEffect(() => { setText(value === undefined ? "" : JSON.stringify(value, null, 1)); }, [name]);  // reload on step switch
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">{label(name, spec, required)} — {spec.description || "JSON"}</Typography>
      <TextField fullWidth multiline minRows={2} value={text} disabled={readOnly} error={bad}
        InputProps={{ sx: { fontFamily: MONO_STACK, fontSize: 12 } }}
        helperText={bad ? "invalid JSON" : undefined}
        onChange={(e) => {
          setText(e.target.value);
          if (e.target.value.trim() === "") { setBad(false); onSet(undefined); return; }
          try { onSet(JSON.parse(e.target.value)); setBad(false); } catch { setBad(true); }
        }} />
    </Box>
  );
}
