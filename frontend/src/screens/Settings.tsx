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
  const [mes, setMes] = useState<MesStatus | null>(null);
  const [sel, setSel] = useState<Record<string, boolean>>({});

  useEffect(() => {
    // MES section is shown only when the module is loaded (404 -> hidden).
    api.get("/mes/status").then(setMes).catch(() => setMes(null));
  }, []);

  const setMesConfig = async (patch: Partial<MesStatus>) => {
    setError(null);
    try { setMes(await api.put("/mes/config", patch)); }
    catch (e: any) { setError(e.message); }
  };

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
