/** Okaya HVT Testbench — hipot recipe editor (app-owned screen override, TEMPLATE.md §1.3 /
 * §1). New/edit screen for the hipot AC-withstand recipe: a domain form (model header, test
 * checklist, per-test parameter panels) instead of the framework's generic step-list editor.
 * Renders inline (left nav stays visible) and reuses the framework API + save flow (POST
 * /recipes → PUT draft → publish). The form body + recipe<->form mapping live in the shared
 * HipotRecipeForm so the read-only detail view matches exactly. */
import { ArrowBack, Save } from "@mui/icons-material";
import { Alert, Box, Button } from "@mui/material";
import { useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { api } from "../../../api/client";
import { useAuth } from "../../../auth/AuthContext";
import { PageHeader } from "../../../components/ui";
import {
  type FormValue, HipotRecipeForm, buildSteps, emptyForm, modelIdError, parseRecipe,
} from "./HipotRecipeForm";

export function HipotRecipeEditor() {
  const navigate = useNavigate();
  const { principal } = useAuth();
  const loc = useLocation();
  const initial = (loc.state as any) || null;
  const r0 = initial?.recipe ?? null;
  // Duplicate = a NEW recipe prefilled from an existing one (the detail page's Duplicate button):
  // it must get its own Model ID, so it is treated as a creation, never as editing the source.
  const isDuplicate = initial?.duplicate === true;

  const [value, setValue] = useState<FormValue>(() => {
    if (!r0) return emptyForm();
    const v = parseRecipe(r0);
    return isDuplicate ? { ...v, modelId: "" } : v;
  });
  // Non-empty only when editing an EXISTING recipe: its ID is then fixed (the form locks it and
  // buildRecipe() ignores whatever the Model ID field holds).
  const recipeId = useMemo(() => (isDuplicate ? "" : r0?.recipe_id || ""), [r0, isDuplicate]);
  const [draftId, setDraftId] = useState<string | null>(initial?.draftId ?? null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  function buildRecipe() {
    const rid = recipeId || value.modelId.trim();
    return {
      schema_version: 1, recipe_id: rid, name: value.model || rid, model: value.model,
      owner: (!isDuplicate && r0?.owner) || principal?.username || "", description: value.description,
      stop_on_fail: value.stopOnFail,
      steps: buildSteps(value),
    };
  }

  async function save() {
    setMsg(null);
    if (!recipeId) {
      const idErr = modelIdError(value.modelId);
      if (idErr) { setMsg({ kind: "error", text: idErr }); return; }
    }
    if (!value.model.trim()) { setMsg({ kind: "error", text: "Enter a model name." }); return; }
    const recipe = buildRecipe();
    if (recipe.steps.length === 0) { setMsg({ kind: "error", text: "Select at least one test." }); return; }
    setBusy(true);
    try {
      const report = await api.post("/recipes/validate", recipe);
      if (report && report.ok === false) {
        setMsg({ kind: "error", text: `Validation: ${(report.errors || []).join("; ") || "invalid recipe"}` });
        return;
      }
      let did = draftId;
      if (!did) { did = (await api.post("/recipes", recipe)).draft_id; setDraftId(did); }
      else await api.put(`/recipes/${recipe.recipe_id}/drafts/${did}`, recipe);
      await api.post(`/recipes/${recipe.recipe_id}/drafts/${did}/publish`);
      setMsg({ kind: "success", text: `Saved recipe "${recipe.recipe_id}".` });
      setTimeout(() => navigate(`/recipes/${recipe.recipe_id}`), 700);
    } catch (e: any) {
      setMsg({ kind: "error", text: e?.message || "Save failed" });
    } finally { setBusy(false); }
  }

  return (
    <Box>
      <PageHeader
        title={recipeId ? `Edit recipe — ${recipeId}`
          : isDuplicate ? `New recipe — copy of ${r0?.recipe_id ?? ""}` : "New recipe"}
        subtitle="Hipot AC-withstand test recipe"
        actions={
          <>
            <Button startIcon={<ArrowBack />} variant="outlined" onClick={() => navigate("/recipes")} disabled={busy}>
              Back
            </Button>
            <Button startIcon={<Save />} variant="contained" onClick={save} disabled={busy}>
              Save
            </Button>
          </>
        }
      />
      {msg && <Alert severity={msg.kind} sx={{ mb: 2 }} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      <HipotRecipeForm value={value} onChange={setValue} idLocked={!!recipeId} />
    </Box>
  );
}
