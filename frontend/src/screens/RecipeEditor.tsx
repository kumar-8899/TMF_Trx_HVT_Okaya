import {
  Add, ArrowDownward, ArrowUpward, Code, DeleteOutline, NavigateBefore, NavigateNext, Search,
} from "@mui/icons-material";
import {
  Alert, Box, Button, Checkbox, Divider, FormControlLabel, IconButton, LinearProgress,
  MenuItem, Paper, Select, Stack, Switch, TextField, ToggleButton, ToggleButtonGroup, Tooltip,
  Typography,
} from "@mui/material";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { PageHeader, Section, StatusDot } from "../components/ui";
import { MONO_STACK } from "../theme/theme";
import { SchemaForm, type Step, type StepType } from "../components/StepEditor";

interface EditState { recipeId: string; draftId: string; recipe: any }
interface Report { ok: boolean; errors: string[]; warnings: string[] }

type StepStatus = "configured" | "partial" | "empty" | "error" | "disabled";
const STATUS_DOT: Record<StepStatus, "pass" | "running" | "idle" | "fail"> = {
  configured: "pass", partial: "running", empty: "idle", error: "fail", disabled: "idle",
};
const ON_FAIL = ["stop", "continue", "retry"];

export function RecipeEditor() {
  const navigate = useNavigate();
  const loc = useLocation();
  const initial = (loc.state as EditState | null) || null;
  const r0 = initial?.recipe ?? {};

  const [recipeId, setRecipeId] = useState(r0.recipe_id || "");
  const [name, setName] = useState(r0.name || "");
  const [owner, setOwner] = useState(r0.owner || "");
  const [description, setDescription] = useState(r0.description || "");
  const [tagsCsv, setTagsCsv] = useState((r0.tags || []).join(", "));
  const [barcodesCsv, setBarcodesCsv] = useState((r0.barcode_prefixes || []).join(", "));
  const [requiredRole, setRequiredRole] = useState(r0.required_role || "");
  const [steps, setSteps] = useState<Step[]>(r0.steps ?? []);
  const [draftId, setDraftId] = useState<string | null>(initial?.draftId ?? null);

  const [types, setTypes] = useState<StepType[]>([]);
  const [schemas, setSchemas] = useState<Record<string, any>>({});
  const [selected, setSelected] = useState(0);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "set" | "empty">("all");
  const [showJson, setShowJson] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [addType, setAddType] = useState("");

  useEffect(() => { api.get("/recipes/step-types").then(setTypes).catch(() => setTypes([])); }, []);

  // Lazy-load (and cache) the resolved schema for every step type in use — drives
  // the parameter form and the "configured vs partial" status in the rail.
  useEffect(() => {
    const need = [...new Set(steps.map((s) => s.step_type))].filter((t) => t && !(t in schemas));
    need.forEach((t) => {
      api.get(`/recipes/step-types/${t}/schema?resolved=true`)
        .then((sc) => setSchemas((m) => ({ ...m, [t]: sc })))
        .catch(() => setSchemas((m) => ({ ...m, [t]: { properties: {}, required: [] } })));
    });
  }, [steps, schemas]);

  // Map validation errors to step ids (best-effort: error text mentions the step_id).
  const errorSet = useMemo(() => {
    const s = new Set<string>();
    for (const e of report?.errors ?? [])
      for (const st of steps) if (st.step_id && e.includes(st.step_id)) s.add(st.step_id);
    return s;
  }, [report, steps]);

  const statusOf = (step: Step): StepStatus => {
    if (step.enabled === false) return "disabled";
    if (errorSet.has(step.step_id)) return "error";
    const keys = Object.keys(step.params ?? {});
    if (keys.length === 0) return "empty";
    const required: string[] = schemas[step.step_type]?.required ?? [];
    const missing = required.some((k) => step.params?.[k] === undefined || step.params?.[k] === "");
    return missing ? "partial" : "configured";
  };

  const configuredCount = steps.filter((s) => statusOf(s) === "configured").length;
  const setCount = steps.filter((s) => Object.keys(s.params ?? {}).length > 0).length;
  const emptyCount = steps.length - setCount;

  const railRows = steps
    .map((s, i) => ({ s, i }))
    .filter(({ s }) => {
      if (filter === "set" && Object.keys(s.params ?? {}).length === 0) return false;
      if (filter === "empty" && Object.keys(s.params ?? {}).length > 0) return false;
      const q = search.toLowerCase().trim();
      return !q || `${s.name ?? ""} ${s.step_id} ${s.step_type}`.toLowerCase().includes(q);
    });

  // --- mutations -------------------------------------------------------------

  const touch = () => setDirty(true);
  const updateStep = (i: number, s: Step) => { setSteps((arr) => arr.map((x, j) => (j === i ? s : x))); touch(); };
  const setField = (i: number, k: keyof Step, v: any) => updateStep(i, { ...steps[i], [k]: v });
  const move = (i: number, d: number) => {
    const j = i + d; if (j < 0 || j >= steps.length) return;
    const copy = [...steps]; [copy[i], copy[j]] = [copy[j], copy[i]];
    setSteps(copy); setSelected(j); touch();
  };
  const remove = (i: number) => {
    setSteps((arr) => arr.filter((_, j) => j !== i));
    setSelected((s) => Math.max(0, s > i ? s - 1 : s)); touch();
  };
  const addStep = (type_id: string) => {
    if (!type_id) return;
    const step: Step = { step_id: `${type_id}_${steps.length + 1}`, step_type: type_id, params: {} };
    setSteps((arr) => [...arr, step]); setSelected(steps.length); setAddType(""); touch();
  };

  const build = (): any => ({
    schema_version: 1, recipe_id: recipeId, name, owner, description,
    tags: tagsCsv.split(",").map((t: string) => t.trim()).filter(Boolean),
    barcode_prefixes: barcodesCsv.split(",").map((t: string) => t.trim()).filter(Boolean),
    ...(requiredRole ? { required_role: requiredRole } : {}),
    steps,
  });

  async function withBusy(fn: () => Promise<void>) {
    setError(null); setBusy(true);
    try { await fn(); } catch (e: any) { setError(e?.message || "Operation failed"); } finally { setBusy(false); }
  }
  const validate = () => withBusy(async () => setReport(await api.post("/recipes/validate", build())));
  const saveDraft = () => withBusy(async () => {
    const payload = build();
    if (!draftId) setDraftId((await api.post("/recipes", payload)).draft_id);
    else await api.put(`/recipes/${recipeId}/drafts/${draftId}`, payload);
    setDirty(false);
  });
  const publish = () => withBusy(async () => {
    const rep: Report = await api.post("/recipes/validate", build());
    setReport(rep);
    if (!rep.ok) return;
    const payload = build();
    let did = draftId;
    if (!did) { did = (await api.post("/recipes", payload)).draft_id; setDraftId(did); }
    else await api.put(`/recipes/${recipeId}/drafts/${did}`, payload);
    await api.post(`/recipes/${recipeId}/drafts/${did}/publish`);
    navigate(`/recipes/${recipeId}`);
  });

  const cur = steps[selected];
  const pct = steps.length ? Math.round((configuredCount / steps.length) * 100) : 0;

  return (
    <Box>
      <PageHeader
        title={draftId ? "Edit draft" : "New recipe"}
        subtitle={recipeId ? `${recipeId}${dirty ? " · unsaved changes" : ""}` : "Author and version a test recipe"}
        actions={
          <>
            <Tooltip title="Edit raw JSON"><IconButton onClick={() => setShowJson((v) => !v)} aria-label="toggle json" color={showJson ? "primary" : "default"}><Code /></IconButton></Tooltip>
            <Button onClick={validate} disabled={busy} variant="outlined">Validate</Button>
            <Button onClick={saveDraft} disabled={busy} variant="outlined">
              {dirty ? "Save draft *" : "Save draft"}
            </Button>
            <Button onClick={publish} disabled={busy} variant="contained">Publish</Button>
          </>
        }
      />

      {/* Recipe-level header strip + progress */}
      <Section sx={{ mb: 2 }}>
        <Stack spacing={2}>
          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
            <TextField label="Recipe ID" value={recipeId} disabled={Boolean(initial)} sx={{ width: 200 }}
              onChange={(e) => { setRecipeId(e.target.value); touch(); }} inputProps={{ "aria-label": "recipe_id" }} />
            <TextField label="Name" value={name} sx={{ flex: 1, minWidth: 200 }}
              onChange={(e) => { setName(e.target.value); touch(); }} />
            <TextField label="Required role" value={requiredRole} sx={{ width: 160 }}
              onChange={(e) => { setRequiredRole(e.target.value); touch(); }} />
          </Stack>
          <TextField label="Description" value={description} multiline minRows={1}
            onChange={(e) => { setDescription(e.target.value); touch(); }} />
          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
            <TextField label="Owner" value={owner} sx={{ width: 200 }} onChange={(e) => { setOwner(e.target.value); touch(); }} />
            <TextField label="Tags (comma-sep)" value={tagsCsv} sx={{ flex: 1, minWidth: 180 }} onChange={(e) => { setTagsCsv(e.target.value); touch(); }} />
            <TextField label="Barcode prefixes" value={barcodesCsv} sx={{ flex: 1, minWidth: 180 }} onChange={(e) => { setBarcodesCsv(e.target.value); touch(); }} />
          </Stack>
          <Box>
            <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.5 }}>
              <Typography variant="caption" color="text.secondary">Configuration progress</Typography>
              <Typography variant="caption" color="text.secondary">{configuredCount} of {steps.length} steps configured</Typography>
            </Stack>
            <LinearProgress variant="determinate" value={pct} color={pct === 100 ? "success" : "primary"}
              sx={{ height: 8, borderRadius: 4 }} />
          </Box>
        </Stack>
      </Section>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {report && (
        <Stack spacing={1} sx={{ mb: 2 }}>
          {report.errors.map((e, i) => <Alert key={i} severity="error">{e}</Alert>)}
          {report.warnings.map((w, i) => <Alert key={i} severity="warning">{w}</Alert>)}
          {report.ok && report.errors.length === 0 && <Alert severity="success">Valid.</Alert>}
        </Stack>
      )}

      {showJson ? (
        <Section title="Steps (raw JSON)">
          <TextField fullWidth multiline minRows={16} value={JSON.stringify(steps, null, 2)}
            sx={{ "& textarea": { fontFamily: MONO_STACK, fontSize: 13 } }} inputProps={{ "aria-label": "steps-json" }}
            onChange={(e) => { try { setSteps(JSON.parse(e.target.value)); touch(); } catch { /* wait for valid */ } }} />
        </Section>
      ) : (
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems="stretch">
          {/* Left rail — the only navigation */}
          <Paper sx={{ width: { xs: "100%", md: 300 }, flexShrink: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            <Box sx={{ bgcolor: "sectionHeader", color: "onNavy", px: 1.5, py: 1.25 }}>
              <Typography variant="subtitle2" sx={{ color: "onNavy" }}>Steps ({steps.length})</Typography>
            </Box>
            <Box sx={{ p: 1.5, pb: 1 }}>
              <TextField fullWidth size="small" placeholder="Search steps…" value={search}
                onChange={(e) => setSearch(e.target.value)}
                InputProps={{ startAdornment: <Search fontSize="small" sx={{ mr: 0.5, color: "text.secondary" }} /> }} />
              <ToggleButtonGroup exclusive size="small" value={filter} onChange={(_, v) => v && setFilter(v)} sx={{ mt: 1 }} fullWidth>
                <ToggleButton value="all">All {steps.length}</ToggleButton>
                <ToggleButton value="set">Set {setCount}</ToggleButton>
                <ToggleButton value="empty">Empty {emptyCount}</ToggleButton>
              </ToggleButtonGroup>
            </Box>
            <Divider />
            <Box sx={{ flex: 1, overflowY: "auto", maxHeight: { md: "56vh" } }}>
              {railRows.length === 0 ? (
                <Typography variant="caption" color="text.secondary" sx={{ display: "block", p: 2, textAlign: "center" }}>
                  {steps.length ? "No steps match." : "No steps yet."}
                </Typography>
              ) : railRows.map(({ s, i }) => {
                const st = statusOf(s);
                const sel = i === selected;
                return (
                  <Box key={i} onClick={() => setSelected(i)} sx={{
                    px: 1.5, py: 1, cursor: "pointer", display: "flex", alignItems: "center", gap: 1,
                    borderLeft: "3px solid", borderLeftColor: sel ? "primary.main" : "transparent",
                    bgcolor: sel ? (t) => (t.palette.mode === "dark" ? "rgba(30,158,87,0.12)" : "rgba(26,107,60,0.07)") : "transparent",
                    opacity: st === "disabled" ? 0.5 : 1,
                    "&:hover": { bgcolor: sel ? undefined : "action.hover" },
                  }}>
                    <StatusDot kind={STATUS_DOT[st]} />
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Typography variant="body2" noWrap sx={{ fontWeight: 600, textDecoration: st === "disabled" ? "line-through" : "none" }}>
                        {s.name || s.step_id}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block", fontFamily: MONO_STACK }}>
                        {s.step_type}
                      </Typography>
                    </Box>
                  </Box>
                );
              })}
            </Box>
            <Divider />
            <Stack direction="row" spacing={1} sx={{ p: 1.5 }} alignItems="center">
              <Select size="small" displayEmpty value={addType} onChange={(e) => setAddType(e.target.value)}
                sx={{ flex: 1 }} inputProps={{ "aria-label": "step type" }}>
                <MenuItem value=""><em>add step…</em></MenuItem>
                {types.map((t) => <MenuItem key={t.type_id} value={t.type_id}>{t.type_id}</MenuItem>)}
              </Select>
              <Button size="small" variant="contained" startIcon={<Add />} disabled={!addType} onClick={() => addStep(addType)}>Add</Button>
            </Stack>
          </Paper>

          {/* Right pane — the selected step */}
          <Box sx={{ flex: 1, minWidth: 0 }}>
            {!cur ? (
              <Section><Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: "center" }}>
                Select a step on the left, or add one to begin.
              </Typography></Section>
            ) : (
              <Stack spacing={2}>
                <Section
                  title={cur.step_type}
                  subtitle={`Step ${selected + 1} of ${steps.length}`}
                  actions={
                    <Stack direction="row" spacing={0.5} alignItems="center">
                      <FormControlLabel sx={{ color: "onNavy", mr: 0.5 }} control={
                        <Switch size="small" checked={cur.enabled !== false}
                          onChange={(e) => setField(selected, "enabled", e.target.checked)} />
                      } label={<Typography variant="caption" sx={{ color: "onNavy" }}>Enabled</Typography>} />
                      <Tooltip title="Move up"><span><IconButton size="small" sx={{ color: "onNavy" }} disabled={selected === 0} onClick={() => move(selected, -1)}><ArrowUpward fontSize="small" /></IconButton></span></Tooltip>
                      <Tooltip title="Move down"><span><IconButton size="small" sx={{ color: "onNavy" }} disabled={selected >= steps.length - 1} onClick={() => move(selected, 1)}><ArrowDownward fontSize="small" /></IconButton></span></Tooltip>
                      <Tooltip title="Delete step"><IconButton size="small" sx={{ color: "onNavy" }} onClick={() => remove(selected)}><DeleteOutline fontSize="small" /></IconButton></Tooltip>
                    </Stack>
                  }
                >
                  {/* Test metadata strip */}
                  <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                    <TextField label="step_id" value={cur.step_id} sx={{ width: 200 }}
                      onChange={(e) => setField(selected, "step_id", e.target.value)} />
                    <TextField label="name" value={cur.name ?? ""} sx={{ flex: 1, minWidth: 200 }}
                      onChange={(e) => setField(selected, "name", e.target.value)} />
                    <TextField label="timeout_ms" type="number" value={(cur as any).timeout_ms ?? ""} sx={{ width: 130 }}
                      onChange={(e) => setField(selected, "timeout_ms" as keyof Step, e.target.value === "" ? undefined : Number(e.target.value))} />
                    <TextField label="retry_count" type="number" value={(cur as any).retry_count ?? ""} sx={{ width: 130 }}
                      onChange={(e) => setField(selected, "retry_count" as keyof Step, e.target.value === "" ? undefined : Number(e.target.value))} />
                    <TextField select label="on_fail" value={(cur as any).on_fail ?? ""} sx={{ width: 140 }}
                      onChange={(e) => setField(selected, "on_fail" as keyof Step, e.target.value || undefined)}>
                      <MenuItem value=""><em>default</em></MenuItem>
                      {ON_FAIL.map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
                    </TextField>
                    <FormControlLabel control={
                      <Checkbox checked={Boolean((cur as any).safety_critical)}
                        onChange={(e) => setField(selected, "safety_critical" as keyof Step, e.target.checked)} />
                    } label="safety critical" />
                  </Stack>
                </Section>

                <Section title="Parameters" subtitle={schemas[cur.step_type] ? undefined : "loading schema…"}>
                  {schemas[cur.step_type]
                    ? <SchemaForm schema={schemas[cur.step_type]} value={cur.params ?? {}}
                        onChange={(p) => setField(selected, "params", p)} types={types} />
                    : <Typography variant="caption" color="text.secondary">loading…</Typography>}
                </Section>

                <Stack direction="row" justifyContent="space-between">
                  <Button startIcon={<NavigateBefore />} disabled={selected === 0} onClick={() => setSelected((s) => s - 1)}>Previous</Button>
                  <Button endIcon={<NavigateNext />} disabled={selected >= steps.length - 1} onClick={() => setSelected((s) => s + 1)}>Next</Button>
                </Stack>
              </Stack>
            )}
          </Box>
        </Stack>
      )}
    </Box>
  );
}
