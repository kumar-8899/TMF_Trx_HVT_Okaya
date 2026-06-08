import {
  Alert, Box, Button, Chip, MenuItem, Paper, Stack, TextField, Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";

export function RecipeDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { can } = useAuth();
  const [versions, setVersions] = useState<{ version: number; content_hash: string }[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [recipe, setRecipe] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  const [from, setFrom] = useState(0);
  const [to, setTo] = useState(0);
  const [diffResult, setDiff] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const loadVersion = useCallback(async (n: number) => {
    setSelected(n);
    setReport(null);
    setRecipe(await api.get(`/recipes/${id}/versions/${n}`));
  }, [id]);

  useEffect(() => {
    api.get(`/recipes/${id}/versions`).then((vs) => {
      setVersions(vs);
      if (vs.length) {
        const latest = vs[vs.length - 1].version;
        setFrom(vs[0].version);
        setTo(latest);
        loadVersion(latest);
      }
    }).catch((e) => setError(e.message));
  }, [id, loadVersion]);

  const validate = async () => {
    try { setReport(await api.post(`/recipes/${id}/versions/${selected}/validate`)); }
    catch (e: any) { setError(e.message); }
  };
  const runDiff = async () => {
    try { setDiff(await api.get(`/recipes/${id}/diff?from_=${from}&to=${to}`)); }
    catch (e: any) { setError(e.message); }
  };
  const fork = async () => {
    const res = await api.post(`/recipes/${id}/drafts`);
    navigate(`/recipes/${id}/edit`, { state: { recipeId: id, draftId: res.draft_id, recipe: res.recipe } });
  };

  return (
    <Stack spacing={2}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="h5">{id}</Typography>
        {can("RECIPE.EDIT") && <Button variant="contained" onClick={fork}>Fork draft</Button>}
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}

      <Stack direction="row" spacing={1} flexWrap="wrap">
        {versions.map((v) => (
          <Chip key={v.version} label={`v${v.version}`} onClick={() => loadVersion(v.version)}
            color={selected === v.version ? "primary" : "default"} />
        ))}
        {versions.length === 0 && <Typography>No published versions.</Typography>}
      </Stack>

      {recipe && (
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle1">{recipe.name} — v{recipe.version}</Typography>
          <Typography variant="caption" color="text.secondary">{recipe.content_hash}</Typography>
          <Box component="pre" sx={{ overflow: "auto", fontSize: 12, mt: 1 }}>
            {JSON.stringify(recipe.steps, null, 2)}
          </Box>
          <Button size="small" onClick={validate}>Validate</Button>
          {report && (
            <Box sx={{ mt: 1 }}>
              {report.ok && <Alert severity="success">Valid.</Alert>}
              {report.errors?.map((e: string, i: number) => <Alert key={i} severity="error">{e}</Alert>)}
              {report.warnings?.map((w: string, i: number) => <Alert key={i} severity="warning">{w}</Alert>)}
            </Box>
          )}
        </Paper>
      )}

      {versions.length >= 2 && (
        <Paper sx={{ p: 2 }}>
          <Stack direction="row" spacing={2} alignItems="center">
            <Typography>Diff</Typography>
            <TextField select size="small" label="from" value={from} onChange={(e) => setFrom(Number(e.target.value))}>
              {versions.map((v) => <MenuItem key={v.version} value={v.version}>v{v.version}</MenuItem>)}
            </TextField>
            <TextField select size="small" label="to" value={to} onChange={(e) => setTo(Number(e.target.value))}>
              {versions.map((v) => <MenuItem key={v.version} value={v.version}>v{v.version}</MenuItem>)}
            </TextField>
            <Button size="small" onClick={runDiff}>Compare</Button>
          </Stack>
          {diffResult && (
            <Box component="pre" sx={{ overflow: "auto", fontSize: 12, mt: 1 }}>
              {JSON.stringify(diffResult, null, 2)}
            </Box>
          )}
        </Paper>
      )}
    </Stack>
  );
}
