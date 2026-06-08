import {
  Alert, Box, Button, Stack, TextField, Typography,
} from "@mui/material";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { api } from "../api/client";

interface EditState {
  recipeId: string;
  draftId: string;
  recipe: any;
}

interface Report {
  ok: boolean;
  errors: string[];
  warnings: string[];
}

export function RecipeEditor() {
  const navigate = useNavigate();
  const loc = useLocation();
  const initial = (loc.state as EditState | null) || null;

  const [recipeId, setRecipeId] = useState(initial?.recipe?.recipe_id || "");
  const [name, setName] = useState(initial?.recipe?.name || "");
  const [owner, setOwner] = useState(initial?.recipe?.owner || "");
  const [tagsCsv, setTagsCsv] = useState((initial?.recipe?.tags || []).join(", "));
  const [stepsText, setStepsText] = useState(
    JSON.stringify(initial?.recipe?.steps ?? [], null, 2),
  );
  const [draftId, setDraftId] = useState<string | null>(initial?.draftId ?? null);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function build(): any {
    return {
      schema_version: 1,
      recipe_id: recipeId,
      name,
      owner,
      tags: tagsCsv.split(",").map((t: string) => t.trim()).filter(Boolean),
      steps: JSON.parse(stepsText),
    };
  }

  async function withBusy(fn: () => Promise<void>) {
    setError(null);
    setBusy(true);
    try {
      await fn();
    } catch (e: any) {
      if (e instanceof SyntaxError) setError("Steps is not valid JSON");
      else setError(e?.message || "Operation failed");
    } finally {
      setBusy(false);
    }
  }

  const validate = () =>
    withBusy(async () => setReport(await api.post("/recipes/validate", build())));

  const saveDraft = () =>
    withBusy(async () => {
      const payload = build();
      if (!draftId) {
        const res = await api.post("/recipes", payload);
        setDraftId(res.draft_id);
      } else {
        await api.put(`/recipes/${recipeId}/drafts/${draftId}`, payload);
      }
    });

  const publish = () =>
    withBusy(async () => {
      const rep: Report = await api.post("/recipes/validate", build());
      setReport(rep);
      if (!rep.ok) return; // block on errors; warnings are fine
      const payload = build();
      let did = draftId;
      if (!did) {
        const res = await api.post("/recipes", payload);
        did = res.draft_id;
        setDraftId(did);
      } else {
        await api.put(`/recipes/${recipeId}/drafts/${did}`, payload);
      }
      await api.post(`/recipes/${recipeId}/drafts/${did}/publish`);
      navigate(`/recipes/${recipeId}`);
    });

  return (
    <Stack spacing={2} sx={{ maxWidth: 800 }}>
      <Typography variant="h5">{draftId ? "Edit draft" : "New recipe"}</Typography>
      <Stack direction="row" spacing={2}>
        <TextField label="Recipe ID" value={recipeId} disabled={Boolean(initial)}
          onChange={(e) => setRecipeId(e.target.value)} inputProps={{ "aria-label": "recipe_id" }} />
        <TextField label="Name" value={name} fullWidth onChange={(e) => setName(e.target.value)} />
      </Stack>
      <Stack direction="row" spacing={2}>
        <TextField label="Owner" value={owner} onChange={(e) => setOwner(e.target.value)} />
        <TextField label="Tags (comma-sep)" value={tagsCsv} fullWidth
          onChange={(e) => setTagsCsv(e.target.value)} />
      </Stack>
      <TextField label="Steps (JSON)" value={stepsText} multiline minRows={10}
        onChange={(e) => setStepsText(e.target.value)} inputProps={{ "aria-label": "steps" }}
        sx={{ fontFamily: "monospace" }} />

      {error && <Alert severity="error">{error}</Alert>}
      {report && (
        <Box>
          {report.errors.map((e, i) => <Alert key={i} severity="error">{e}</Alert>)}
          {report.warnings.map((w, i) => <Alert key={i} severity="warning">{w}</Alert>)}
          {report.ok && report.errors.length === 0 && <Alert severity="success">Valid.</Alert>}
        </Box>
      )}

      <Stack direction="row" spacing={2}>
        <Button onClick={validate} disabled={busy}>Validate</Button>
        <Button onClick={saveDraft} disabled={busy} variant="outlined">Save draft</Button>
        <Button onClick={publish} disabled={busy} variant="contained">Publish</Button>
      </Stack>
    </Stack>
  );
}
