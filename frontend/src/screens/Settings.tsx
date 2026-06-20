import { DeleteForever } from "@mui/icons-material";
import {
  Alert, Box, Button, Chip, FormControlLabel, Stack, Switch, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { ConfirmDialog, PageHeader, Section } from "../components/ui";
import { MONO_STACK } from "../theme/theme";

interface MesStatus {
  stage: string; provider: string; gate_enabled: boolean; publish_enabled: boolean;
  on_missing: string; provider_detail: Record<string, any>;
}

/** Station settings. Scalable: each concern is its own Section card; add more as
 * the app grows. Reachable only with SYSTEM.RESET_DATA (super_admin) — gated in
 * App.tsx + the nav. */
export function Settings() {
  const [confirmReset, setConfirmReset] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mes, setMes] = useState<MesStatus | null>(null);

  useEffect(() => {
    // MES section is shown only when the module is loaded (404 -> hidden).
    api.get("/mes/status").then(setMes).catch(() => setMes(null));
  }, []);

  const setMesConfig = async (patch: Partial<MesStatus>) => {
    setError(null);
    try { setMes(await api.put("/mes/config", patch)); }
    catch (e: any) { setError(e.message); }
  };

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

        {mes && (
          <Section title="MES interlock" subtitle={`Stage ${mes.stage} · ${mes.provider} transport`}>
            <Stack spacing={1.5}>
              <FormControlLabel
                control={<Switch checked={mes.gate_enabled} onChange={(e) => setMesConfig({ gate_enabled: e.target.checked })} />}
                label={
                  <Box>
                    <Typography variant="subtitle2">Inbound gate</Typography>
                    <Typography variant="body2" color="text.secondary">
                      Block a run unless the unit passed the previous stage ({mes.on_missing} when no upstream record).
                    </Typography>
                  </Box>
                } />
              <FormControlLabel
                control={<Switch checked={mes.publish_enabled} onChange={(e) => setMesConfig({ publish_enabled: e.target.checked })} />}
                label={
                  <Box>
                    <Typography variant="subtitle2">Outbound publish</Typography>
                    <Typography variant="body2" color="text.secondary">
                      Write this stage's result downstream for the next stage on run-finish.
                    </Typography>
                  </Box>
                } />
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Chip size="small" label={`upstream: ${mes.provider_detail?.upstream_dir ?? "—"}`} sx={{ fontFamily: MONO_STACK }} />
                <Chip size="small" label={`downstream: ${mes.provider_detail?.downstream_dir ?? "—"}`} sx={{ fontFamily: MONO_STACK }} />
              </Stack>
            </Stack>
          </Section>
        )}

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
