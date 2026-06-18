import { Alert, Box, Button, Stack } from "@mui/material";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { PageHeader } from "../components/ui";
import { RecipeForm, type RecipeValue } from "../components/RecipeForm";

interface EditState { recipeId: string; draftId: string; recipe: any }
interface Report { ok: boolean; errors: string[]; warnings: string[] }

export function RecipeEditor() {
  const navigate = useNavigate();
  const { principal } = useAuth();
  const loc = useLocation();
  const initial = (loc.state as EditState | null) || null;
  const r0 = initial?.recipe ?? {};

  const [value, setValue] = useState<RecipeValue>({
    recipe_id: r0.recipe_id || "",
    name: r0.name || "",
    // Owner auto-populated with the creator (kept if forking an existing recipe).
    owner: r0.owner || principal?.username || "",
    description: r0.description || "",
    steps: r0.steps ?? [],
  });
  const [draftId, setDraftId] = useState<string | null>(initial?.draftId ?? null);
  const [dirty, setDirty] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Map validation errors back to the tests that mention them (red rail dots).
  const errorIds = new Set<string>();
  for (const e of report?.errors ?? [])
    for (const s of value.steps) if (s.step_id && e.includes(s.step_id)) errorIds.add(s.step_id);

  const onChange = (v: RecipeValue) => { setValue(v); setDirty(true); };

  const build = () => ({
    schema_version: 1,
    recipe_id: value.recipe_id,
    name: value.name,
    owner: value.owner,
    description: value.description,
    steps: value.steps,
  });

  async function withBusy(fn: () => Promise<void>) {
    setError(null); setBusy(true);
    try { await fn(); } catch (e: any) { setError(e?.message || "Operation failed"); } finally { setBusy(false); }
  }
  const validate = () => withBusy(async () => setReport(await api.post("/recipes/validate", build())));
  const saveDraft = () => withBusy(async () => {
    const payload = build();
    if (!draftId) setDraftId((await api.post("/recipes", payload)).draft_id);
    else await api.put(`/recipes/${value.recipe_id}/drafts/${draftId}`, payload);
    setDirty(false);
  });
  const publish = () => withBusy(async () => {
    const rep: Report = await api.post("/recipes/validate", build());
    setReport(rep);
    if (!rep.ok) return;
    const payload = build();
    let did = draftId;
    if (!did) { did = (await api.post("/recipes", payload)).draft_id; setDraftId(did); }
    else await api.put(`/recipes/${value.recipe_id}/drafts/${did}`, payload);
    await api.post(`/recipes/${value.recipe_id}/drafts/${did}/publish`);
    navigate(`/recipes/${value.recipe_id}`);
  });

  return (
    <Box>
      <PageHeader
        title={draftId ? "Edit draft" : "New recipe"}
        subtitle={value.recipe_id ? `${value.recipe_id}${dirty ? " · unsaved changes" : ""}` : "Author a test recipe"}
        actions={
          <>
            <Button onClick={validate} disabled={busy} variant="outlined">Validate</Button>
            <Button onClick={saveDraft} disabled={busy} variant="outlined">{dirty ? "Save draft *" : "Save draft"}</Button>
            <Button onClick={publish} disabled={busy} variant="contained">Publish</Button>
          </>
        }
      />

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {report && (
        <Stack spacing={1} sx={{ mb: 2 }}>
          {report.errors.map((e, i) => <Alert key={i} severity="error">{e}</Alert>)}
          {report.warnings.map((w, i) => <Alert key={i} severity="warning">{w}</Alert>)}
          {report.ok && report.errors.length === 0 && <Alert severity="success">Valid.</Alert>}
        </Stack>
      )}

      <RecipeForm value={value} onChange={onChange} idLocked={Boolean(initial)} errorIds={errorIds} />
    </Box>
  );
}
