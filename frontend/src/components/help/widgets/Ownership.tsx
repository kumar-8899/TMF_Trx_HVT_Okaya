/** `tmf:ownership` — the fork ownership boundary (docs/TEMPLATE.md §1) as a tiny interactive
 * classifier: type any repo path, learn whether an app may edit it or a framework release must. */
import { Alert, Box, Chip, Stack, TextField, Typography } from "@mui/material";
import { useState } from "react";

import { useFacts } from "./facts";

export interface Verdict { owner: "app" | "framework"; rule: string; advice: string }

const APP_RULES: [RegExp, string][] = [
  [/^app\/[^/]+(\/|$)/, "app/<name>/ — the app payload (step types, variable maps, recipes, controller.json, specs)"],
  [/^instrument_libs(\/|$)/, "instrument_libs/ — drivers this app copied from the central Instrument_Library"],
  [/^frontend\/src\/app\/overrides(\/|$)/, "frontend/src/app/overrides/ — per-app screens and pages"],
  [/^labview\/App(\/|$)/, "labview/App/ — application LabVIEW (test cases, HAL)"],
  [/^backend\/config\/(app|license)\.json$/, "live station config + license (gitignored; the framework ships *.example.json)"],
  [/^backend\/config\/known_issues(\/|$)/, "site data"],
  [/^backend\/data(\/|$)/, "runtime data (gitignored)"],
  [/^app\/[^/]+\/help(\/|$)/, "app-owned help pages"],
];

/** `frameworkModules` = ids of the standard framework modules; any OTHER backend/modules/<x>/ is an
 * app module (TEMPLATE.md: prefix app modules with the app name so upstream can never collide). */
export function classifyPath(raw: string, frameworkModules: string[]): Verdict | null {
  const path = raw.trim().replace(/\\/g, "/").replace(/^\.?\//, "");
  if (!path) return null;
  const mod = /^backend\/modules\/([^/]+)(\/|$)/.exec(path);
  if (mod && !frameworkModules.includes(mod[1])) {
    return { owner: "app", rule: `backend/modules/${mod[1]}/ — an app-specific backend module`,
      advice: "Yours. Keep the app-name prefix (e.g. acme_eol) so a later framework module can never collide." };
  }
  for (const [re, rule] of APP_RULES) {
    if (re.test(path)) {
      return { owner: "app", rule, advice: "Yours — edit freely; framework merges never touch it." };
    }
  }
  return {
    owner: "framework",
    rule: mod ? `backend/modules/${mod[1]}/ — a standard framework module`
      : "everything outside the app-owned paths (core, controller, frontend screens, docs, deploy, tools …)",
    advice: "Framework-owned. Don't patch it in the fork — change it in the framework repo and cut a release, "
      + "then `git fetch upstream --tags && git merge vX.Y.Z`. A downstream patch makes every later merge conflict.",
  };
}

const EXAMPLES = [
  "app/acme_eol/recipes/main.json", "instrument_libs/power/tenma.py", "backend/core/app.py",
  "frontend/src/screens/Runs.tsx", "frontend/src/app/overrides/runs.tsx", "backend/modules/acme_eol/api.py",
  "backend/modules/recipe/api.py", "backend/config/app.json", "controller/controller/serve.py",
];

export function OwnershipWidget() {
  const { facts } = useFacts();
  const [path, setPath] = useState("");
  const fw = facts?.modules.map((m) => m.id) ?? ["auth", "config", "health", "help", "logs", "mes", "recipe", "report", "runs", "variables"];
  const v = classifyPath(path, fw);
  return (
    <Box sx={{ my: 2, p: 2, border: "1px solid", borderColor: "divider", borderRadius: 1 }}>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>Who owns this path?</Typography>
      <TextField fullWidth size="small" value={path} onChange={(e) => setPath(e.target.value)}
        placeholder="e.g. backend/core/app.py" inputProps={{ "aria-label": "repo path" }} />
      <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ mt: 1 }}>
        {EXAMPLES.map((e) => <Chip key={e} size="small" variant="outlined" label={e} onClick={() => setPath(e)} />)}
      </Stack>
      {v && (
        <Alert severity={v.owner === "app" ? "success" : "warning"} sx={{ mt: 1.5 }}>
          <strong>{v.owner === "app" ? "App-owned" : "Framework-owned"}</strong> — {v.rule}.<br />{v.advice}
        </Alert>
      )}
    </Box>
  );
}
