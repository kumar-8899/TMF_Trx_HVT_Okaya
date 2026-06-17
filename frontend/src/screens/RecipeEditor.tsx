import {
  Alert, Box, Button, FormControlLabel, Stack, Switch, TextField,
} from "@mui/material";
import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { PageHeader, Section } from "../components/ui";
import { MONO_STACK } from "../theme/theme";
import { Step, StepList, StepType } from "../components/StepEditor";

interface EditState { recipeId: string; draftId: string; recipe: any }
interface Report { ok: boolean; errors: string[]; warnings: string[] }

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
  const [showJson, setShowJson] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.get("/recipes/step-types").then(setTypes).catch(() => setTypes([])); }, []);

  const build = (): any => ({
    schema_version: 1,
    recipe_id: recipeId,
    name,
    owner,
    description,
    tags: tagsCsv.split(",").map((t: string) => t.trim()).filter(Boolean),
    barcode_prefixes: barcodesCsv.split(",").map((t: string) => t.trim()).filter(Boolean),
    ...(requiredRole ? { required_role: requiredRole } : {}),
    steps,
  });

  async function withBusy(fn: () => Promise<void>) {
    setError(null); setBusy(true);
    try { await fn(); }
    catch (e: any) { setError(e?.message || "Operation failed"); }
    finally { setBusy(false); }
  }

  const validate = () => withBusy(async () => setReport(await api.post("/recipes/validate", build())));

  const saveDraft = () => withBusy(async () => {
    const payload = build();
    if (!draftId) setDraftId((await api.post("/recipes", payload)).draft_id);
    else await api.put(`/recipes/${recipeId}/drafts/${draftId}`, payload);
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

  return (
    <Box sx={{ maxWidth: 900 }}>
      <PageHeader title={draftId ? "Edit draft" : "New recipe"} subtitle="Author and version a test recipe" />

      <Stack spacing={2}>
        <Section title="Details">
          <Stack spacing={2}>
            <Stack direction="row" spacing={2}>
              <TextField label="Recipe ID" value={recipeId} disabled={Boolean(initial)}
                onChange={(e) => setRecipeId(e.target.value)} inputProps={{ "aria-label": "recipe_id" }} />
              <TextField label="Name" value={name} fullWidth onChange={(e) => setName(e.target.value)} />
            </Stack>
            <TextField label="Description" value={description} multiline minRows={2}
              onChange={(e) => setDescription(e.target.value)} />
            <Stack direction="row" spacing={2}>
              <TextField label="Owner" value={owner} onChange={(e) => setOwner(e.target.value)} />
              <TextField label="Required role" value={requiredRole} onChange={(e) => setRequiredRole(e.target.value)} />
            </Stack>
            <Stack direction="row" spacing={2}>
              <TextField label="Tags (comma-sep)" value={tagsCsv} fullWidth onChange={(e) => setTagsCsv(e.target.value)} />
              <TextField label="Barcode prefixes (comma-sep)" value={barcodesCsv} fullWidth
                onChange={(e) => setBarcodesCsv(e.target.value)} />
            </Stack>
          </Stack>
        </Section>

        <Section
          title="Steps"
          actions={
            <FormControlLabel control={<Switch checked={showJson} onChange={(e) => setShowJson(e.target.checked)} />}
              label="Edit as JSON" />
          }
        >
          {showJson
            ? <TextField fullWidth multiline minRows={10} value={JSON.stringify(steps, null, 2)}
                sx={{ "& textarea": { fontFamily: MONO_STACK } }} inputProps={{ "aria-label": "steps-json" }}
                onChange={(e) => { try { setSteps(JSON.parse(e.target.value)); } catch { /* wait for valid */ } }} />
            : <StepList steps={steps} onChange={setSteps} types={types} />}
        </Section>

        {error && <Alert severity="error">{error}</Alert>}
        {report && (
          <Stack spacing={1}>
            {report.errors.map((e, i) => <Alert key={i} severity="error">{e}</Alert>)}
            {report.warnings.map((w, i) => <Alert key={i} severity="warning">{w}</Alert>)}
            {report.ok && report.errors.length === 0 && <Alert severity="success">Valid.</Alert>}
          </Stack>
        )}

        <Stack direction="row" spacing={2}>
          <Button onClick={validate} disabled={busy} variant="outlined">Validate</Button>
          <Button onClick={saveDraft} disabled={busy} variant="outlined">Save draft</Button>
          <Button onClick={publish} disabled={busy} variant="contained">Publish</Button>
        </Stack>
      </Stack>
    </Box>
  );
}
