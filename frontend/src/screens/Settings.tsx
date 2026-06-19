import { DeleteForever } from "@mui/icons-material";
import { Alert, Box, Button, Stack, Typography } from "@mui/material";
import { useState } from "react";

import { api } from "../api/client";
import { ConfirmDialog, PageHeader, Section } from "../components/ui";

/** Station settings. Scalable: each concern is its own Section card; add more as
 * the app grows. Reachable only with SYSTEM.RESET_DATA (super_admin) — gated in
 * App.tsx + the nav. */
export function Settings() {
  const [confirmReset, setConfirmReset] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const resetData = async () => {
    setError(null); setNotice(null); setBusy(true);
    try {
      const r = await api.post("/runs/reset-data", {});
      const d = r.deleted || {};
      setNotice(`Reset — ${d.run ?? 0} runs, ${d.run_event ?? 0} events, ${d.report ?? 0} reports, ${d.error_log ?? 0} error logs, ${d.action_log ?? 0} action logs removed.`);
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Box>
      <PageHeader title="Settings" subtitle="Station administration" />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}

      <Stack spacing={2}>
        <Section title="Data management">
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }} justifyContent="space-between">
            <Box>
              <Typography variant="subtitle2">Reset test data</Typography>
              <Typography variant="body2" color="text.secondary">
                Permanently deletes run records, run events, reports, and the error/action
                logs (run history, today's counts, the Reports page, and the Logs page).
                Recipes and users are not affected.
              </Typography>
            </Box>
            <Button color="error" variant="contained" startIcon={<DeleteForever />} disabled={busy}
              onClick={() => setConfirmReset(true)} sx={{ flexShrink: 0 }}>
              Reset data
            </Button>
          </Stack>
        </Section>

        {/* Future settings sections go here. */}
      </Stack>

      <ConfirmDialog
        open={confirmReset}
        title="Reset all test data?"
        body="This permanently deletes every run, run event, and report. This cannot be undone."
        confirmLabel="Reset data"
        danger
        onConfirm={resetData}
        onClose={() => setConfirmReset(false)}
      />
    </Box>
  );
}
