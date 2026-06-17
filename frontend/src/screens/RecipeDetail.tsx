import { CallSplit } from "@mui/icons-material";
import {
  Alert, Box, Button, Chip, MenuItem, Stack, TextField,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageHeader, Section } from "../components/ui";
import { MONO_STACK } from "../theme/theme";

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
    <Box>
      <PageHeader
        title={id}
        subtitle="Recipe versions"
        actions={can("RECIPE.EDIT") && (
          <Button variant="contained" startIcon={<CallSplit />} onClick={fork}>Fork draft</Button>
        )}
      />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Stack spacing={2}>
        <Section title="Versions">
          {versions.length === 0 ? (
            <EmptyState message="No published versions." />
          ) : (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {versions.map((v) => (
                <Chip key={v.version} label={`v${v.version}`} onClick={() => loadVersion(v.version)}
                  color={selected === v.version ? "primary" : "default"}
                  variant={selected === v.version ? "filled" : "outlined"} />
              ))}
            </Stack>
          )}
        </Section>

        {recipe && (
          <Section
            title={`${recipe.name} — v${recipe.version}`}
            subtitle={recipe.content_hash}
            actions={<Button size="small" variant="outlined" onClick={validate}>Validate</Button>}
          >
            {report && (
              <Stack spacing={1} sx={{ mb: 1.5 }}>
                {report.ok && <Alert severity="success">Valid.</Alert>}
                {report.errors?.map((e: string, i: number) => <Alert key={i} severity="error">{e}</Alert>)}
                {report.warnings?.map((w: string, i: number) => <Alert key={i} severity="warning">{w}</Alert>)}
              </Stack>
            )}
            <Box component="pre" sx={{
              overflow: "auto", fontSize: 12, fontFamily: MONO_STACK, m: 0, p: 1.5, borderRadius: 1,
              bgcolor: (t) => (t.palette.mode === "dark" ? "rgba(255,255,255,0.04)" : "rgba(2,6,23,0.04)"),
            }}>
              {JSON.stringify(recipe.steps, null, 2)}
            </Box>
          </Section>
        )}

        {versions.length >= 2 && (
          <Section title="Compare versions">
            <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
              <TextField select label="from" value={from} onChange={(e) => setFrom(Number(e.target.value))} sx={{ width: 100 }}>
                {versions.map((v) => <MenuItem key={v.version} value={v.version}>v{v.version}</MenuItem>)}
              </TextField>
              <TextField select label="to" value={to} onChange={(e) => setTo(Number(e.target.value))} sx={{ width: 100 }}>
                {versions.map((v) => <MenuItem key={v.version} value={v.version}>v{v.version}</MenuItem>)}
              </TextField>
              <Button variant="outlined" onClick={runDiff}>Compare</Button>
            </Stack>
            {diffResult && (
              <Box component="pre" sx={{ overflow: "auto", fontSize: 12, fontFamily: MONO_STACK, mt: 1.5 }}>
                {JSON.stringify(diffResult, null, 2)}
              </Box>
            )}
          </Section>
        )}
      </Stack>
    </Box>
  );
}
