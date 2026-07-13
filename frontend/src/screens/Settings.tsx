import { DeleteForever } from "@mui/icons-material";
import {
  Alert, Box, Button, FormControlLabel, Stack, Switch, Typography,
} from "@mui/material";
import { useState } from "react";

import { api } from "../api/client";
import { ConfirmDialog, PageHeader, Section } from "../components/ui";
import { LicenseConfig } from "./config/LicenseConfig";
import { ReportDbConfig } from "./config/ReportDbConfig";

const RESET_ITEMS = [
  { key: "runs", label: "Runs & history", desc: "Run records + run events (run history, today's counts)." },
  { key: "reports", label: "Reports", desc: "Per-run reports + analytics inputs." },
  { key: "logs", label: "Logs", desc: "Error and action logs (the Logs page)." },
  { key: "recipes", label: "Recipes", desc: "All recipes and their versions." },
  { key: "users", label: "Users", desc: "All users except the super_admin." },
];

/** Station settings. Scalable: each concern is its own Section card; add more as
 * the app grows. Reachable only with SYSTEM.RESET_DATA (super_admin) — gated in
 * App.tsx + the nav. */
export function Settings() {
  const [confirmReset, setConfirmReset] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState<Record<string, boolean>>({});

  const targets = Object.keys(sel).filter((k) => sel[k]);
  const resetData = async () => {
    setError(null); setNotice(null); setBusy(true);
    try {
      const r = await api.post("/runs/reset-data", { targets });
      const d = r.deleted || {};
      setNotice(`Reset complete — ${Object.entries(d).map(([k, v]) => `${k}: ${v}`).join(", ") || "nothing"}.`);
      setSel({});
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Box>
      <PageHeader title="Settings" subtitle="Station administration" />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}

      <Stack spacing={2}>
        <Section title="Data management" subtitle="Select what to permanently delete, then reset">
          <Stack spacing={0.5}>
            {RESET_ITEMS.map((it) => (
              <FormControlLabel key={it.key}
                control={<Switch checked={Boolean(sel[it.key])} onChange={(e) => setSel({ ...sel, [it.key]: e.target.checked })} />}
                label={
                  <Box>
                    <Typography variant="subtitle2">{it.label}</Typography>
                    <Typography variant="body2" color="text.secondary">{it.desc}</Typography>
                  </Box>
                } />
            ))}
          </Stack>
          <Box sx={{ mt: 2 }}>
            <Button color="error" variant="contained" startIcon={<DeleteForever />} disabled={busy || targets.length === 0}
              onClick={() => setConfirmReset(true)}>
              Reset selected ({targets.length})
            </Button>
          </Box>
        </Section>

        <LicenseConfig />

        <ReportDbConfig />

        {/* MES interlock moved to Config → MES. Future settings sections go here. */}
      </Stack>

      <ConfirmDialog
        open={confirmReset}
        title="Reset selected data?"
        body={`Permanently delete: ${targets.map((t) => RESET_ITEMS.find((i) => i.key === t)?.label || t).join(", ")}. This cannot be undone.`}
        confirmLabel="Reset"
        danger
        onConfirm={resetData}
        onClose={() => setConfirmReset(false)}
      />
    </Box>
  );
}
