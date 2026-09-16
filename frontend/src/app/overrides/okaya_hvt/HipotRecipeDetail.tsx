/** Okaya HVT hipot recipe — read-only detail view (app-owned screen override for the
 * `recipe-detail` key, TEMPLATE.md §1.3). Replaces the framework's generic step-list detail so
 * VIEWING a recipe shows the same hipot form as authoring it, read-only. Keeps the framework's
 * version chips + actions (Validate / Deactivate / Duplicate / Edit) and data flow; Edit routes
 * to /recipes/:id/edit, which is the hipot editor override. */
import { Block, ContentCopy, Edit } from "@mui/icons-material";
import { Alert, Box, Button, Chip, Stack, Typography } from "@mui/material";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../../../api/client";
import { useAuth } from "../../../auth/AuthContext";
import { PageHeader, Section } from "../../../components/ui";
import { HipotRecipeForm, emptyForm, parseRecipe } from "./HipotRecipeForm";

export function HipotRecipeDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { can } = useAuth();
  const [versions, setVersions] = useState<{ version: number; content_hash: string }[]>([]);
  const [selectedVer, setSelectedVer] = useState<number | null>(null);
  const [recipe, setRecipe] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const loadVersion = useCallback(async (n: number) => {
    setSelectedVer(n); setReport(null);
    setRecipe(await api.get(`/recipes/${id}/versions/${n}`));
  }, [id]);

  useEffect(() => {
    api.get(`/recipes/${id}/versions`).then((vs) => {
      setVersions(vs);
      if (vs.length) loadVersion(vs[vs.length - 1].version);
    }).catch((e) => setError(e.message));
  }, [id, loadVersion]);

  const value = useMemo(() => (recipe ? parseRecipe(recipe) : emptyForm()), [recipe]);

  const validate = async () => {
    try { setReport(await api.post(`/recipes/${id}/versions/${selectedVer}/validate`)); }
    catch (e: any) { setError(e.message); }
  };
  const edit = async () => {
    setError(null);
    try {
      const res = await api.post(`/recipes/${id}/drafts`);
      navigate(`/recipes/${id}/edit`, { state: { recipeId: id, draftId: res.draft_id, recipe: res.recipe } });
    } catch (e: any) { setError(e.message); }
  };
  const duplicate = () =>
    navigate("/recipes/new", { state: { recipe: { ...recipe, recipe_id: id }, duplicate: true } });
  const deprecate = async () => {
    setError(null);
    try { await api.post(`/recipes/${id}/deprecate`, { reason: "deactivated from UI" }); navigate("/recipes"); }
    catch (e: any) { setError(e.message); }
  };

  return (
    <Box>
      <PageHeader
        title={id}
        subtitle={recipe ? `${recipe.name} — v${recipe.version} · read only` : "Recipe — read only"}
        actions={
          <>
            {selectedVer != null && <Button variant="outlined" onClick={validate}>Validate</Button>}
            {can("RECIPE.EDIT") && <Button variant="outlined" color="warning" startIcon={<Block />} onClick={deprecate}>Deactivate</Button>}
            {can("RECIPE.EDIT") && <Button variant="outlined" startIcon={<ContentCopy />} onClick={duplicate}>Duplicate</Button>}
            {can("RECIPE.EDIT") && <Button variant="contained" startIcon={<Edit />} onClick={edit}>Edit (new version)</Button>}
          </>
        }
      />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Stack spacing={2}>
        {versions.length > 1 && (
          <Section title="Versions">
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {versions.map((v) => (
                <Chip key={v.version} label={`v${v.version}`} onClick={() => loadVersion(v.version)}
                  color={selectedVer === v.version ? "primary" : "default"}
                  variant={selectedVer === v.version ? "filled" : "outlined"} />
              ))}
            </Stack>
          </Section>
        )}

        {report && (
          <Stack spacing={1}>
            {report.ok && <Alert severity="success">Valid.</Alert>}
            {report.errors?.map((e: string, i: number) => <Alert key={i} severity="error">{e}</Alert>)}
            {report.warnings?.map((w: string, i: number) => <Alert key={i} severity="warning">{w}</Alert>)}
          </Stack>
        )}

        {recipe ? (
          <HipotRecipeForm value={value} readOnly />
        ) : (
          !error && <Typography color="text.secondary">Loading…</Typography>
        )}
      </Stack>
    </Box>
  );
}
