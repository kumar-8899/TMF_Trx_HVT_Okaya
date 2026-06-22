import { Block, ContentCopy } from "@mui/icons-material";
import { Alert, Box, Button, Chip, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { PageHeader, Section } from "../components/ui";
import { RecipeForm, type RecipeValue } from "../components/RecipeForm";
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
    setSelected(n); setReport(null); setDiff(null);
    setRecipe(await api.get(`/recipes/${id}/versions/${n}`));
  }, [id]);

  useEffect(() => {
    api.get(`/recipes/${id}/versions`).then((vs) => {
      setVersions(vs);
      if (vs.length) {
        const latest = vs[vs.length - 1].version;
        setFrom(vs[0].version); setTo(latest); loadVersion(latest);
      }
    }).catch((e) => setError(e.message));
  }, [id, loadVersion]);

  const validate = async () => {
    try { setReport(await api.post(`/recipes/${id}/versions/${selected}/validate`)); }
    catch (e: any) { setError(e.message); }
  };
  const runDiff = async () => {
    try { setDiff(await api.get(`/recipes/${id}/diff?from=${from}&to=${to}`)); }
    catch (e: any) { setError(e.message); }
  };
  const duplicate = () => {
    // copy the selected version into a fresh, editable-id recipe
    navigate("/recipes/new", { state: { recipe: { ...recipe, recipe_id: id }, duplicate: true } });
  };
  const deprecate = async () => {
    setError(null);
    try { await api.post(`/recipes/${id}/deprecate`, { reason: "deactivated from UI" }); navigate("/recipes"); }
    catch (e: any) { setError(e.message); }
  };

  const value: RecipeValue | null = recipe && {
    recipe_id: id, name: recipe.name, owner: recipe.owner, description: recipe.description,
    steps: recipe.steps ?? [],
  };

  return (
    <Box>
      <PageHeader
        title={id}
        subtitle="Recipe — read only"
        actions={
          <>
            {selected != null && <Button variant="outlined" onClick={validate}>Validate</Button>}
            {can("RECIPE.EDIT") && <Button variant="outlined" color="warning" startIcon={<Block />} onClick={deprecate}>Deactivate</Button>}
            {can("RECIPE.EDIT") && <Button variant="contained" startIcon={<ContentCopy />} onClick={duplicate}>Duplicate</Button>}
          </>
        }
      />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Stack spacing={2}>
        <Section title="Versions">
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
            {versions.map((v) => (
              <Chip key={v.version} label={`v${v.version}`} onClick={() => loadVersion(v.version)}
                color={selected === v.version ? "primary" : "default"}
                variant={selected === v.version ? "filled" : "outlined"} />
            ))}
            {versions.length >= 2 && (
              <>
                <Box sx={{ flexGrow: 1 }} />
                <TextField select size="small" label="from" value={from} onChange={(e) => setFrom(Number(e.target.value))} sx={{ width: 90 }}>
                  {versions.map((v) => <MenuItem key={v.version} value={v.version}>v{v.version}</MenuItem>)}
                </TextField>
                <TextField select size="small" label="to" value={to} onChange={(e) => setTo(Number(e.target.value))} sx={{ width: 90 }}>
                  {versions.map((v) => <MenuItem key={v.version} value={v.version}>v{v.version}</MenuItem>)}
                </TextField>
                <Button size="small" variant="outlined" onClick={runDiff}>Compare</Button>
              </>
            )}
          </Stack>
          {diffResult && (
            <Box component="pre" sx={{ overflow: "auto", fontSize: 12, fontFamily: MONO_STACK, mt: 1.5 }}>
              {JSON.stringify(diffResult, null, 2)}
            </Box>
          )}
        </Section>

        {report && (
          <Stack spacing={1}>
            {report.ok && <Alert severity="success">Valid.</Alert>}
            {report.errors?.map((e: string, i: number) => <Alert key={i} severity="error">{e}</Alert>)}
            {report.warnings?.map((w: string, i: number) => <Alert key={i} severity="warning">{w}</Alert>)}
          </Stack>
        )}

        {value && (
          <>
            <Typography variant="subtitle1" fontWeight={600}>{recipe.name} — v{recipe.version}</Typography>
            <RecipeForm value={value} readOnly idLocked />
          </>
        )}
      </Stack>
    </Box>
  );
}
