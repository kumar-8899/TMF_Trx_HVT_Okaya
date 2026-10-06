/** MES interlock config (Config → MES).
 * Transport: Folder (file handoff) or Database (customer tables). In Database mode Inbound (the gate) and
 * Outbound (publish) are each a guided process; either can be switched off independently. */
import {
  Alert, Box, Chip, FormControlLabel, MenuItem, Stack, Switch, TextField, ToggleButton,
  ToggleButtonGroup, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api, ApiError } from "../../api/client";
import { EmptyState, PageHeader, Section } from "../../components/ui";
import { MONO_STACK } from "../../theme/theme";
import { InboundCard, type InboundCfg } from "./mes/InboundCard";
import { OutboundCard, type MesField, type OutboundCfg } from "./mes/OutboundCard";

interface MesStatus {
  stage: string; provider: string; gate_enabled: boolean; publish_enabled: boolean;
  on_missing: string; on_error: string; provider_detail: Record<string, any>; failed_pushes: number;
}
interface DbConfig { inbound?: InboundCfg; outbound?: OutboundCfg; fields?: MesField[] }

export function ConfigMes() {
  const [mes, setMes] = useState<MesStatus | null>(null);
  const [db, setDb] = useState<DbConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    Promise.all([api.get("/mes/status"), api.get("/mes/db-config")])
      .then(([m, d]) => { setMes(m); setDb(d); })
      .catch((e: any) => {
        // 403 = signed in but lacks "Station settings"; 404 = the MES module isn't loaded. Say which.
        if (e instanceof ApiError && e.status === 403) setProblem("You need the “Station settings” permission to configure MES.");
        else if (e instanceof ApiError && e.status !== 404) setProblem(e.message);
      })
      .finally(() => setLoaded(true));
  }, []);

  const setMesConfig = async (patch: Record<string, unknown>) => {
    setError(null);
    try { setMes(await api.put("/mes/config", patch)); }
    catch (e: any) { setError(e.message); }
  };

  const isDb = mes?.provider === "database";

  return (
    <Box>
      <PageHeader title="MES interlock" subtitle="Cross-station gate & publish" />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {problem && <Alert severity="warning" sx={{ mb: 2 }}>{problem}</Alert>}
      {!mes ? (loaded && !problem && <Section><EmptyState message="MES module is not enabled on this station." /></Section>) : (
        <Stack spacing={2}>
          {mes.failed_pushes > 0 && (
            <Alert severity="error">
              {mes.failed_pushes} finished run(s) could not be sent to MES. Use <b>Retry</b> in the prompt that appears on
              every screen, or fix the outbound settings below first.
            </Alert>
          )}
          <Section title="MES interlock" subtitle={`Stage ${mes.stage} · ${mes.provider} transport`}>
            <Stack spacing={2}>
              <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
                <Typography variant="subtitle2">Transport</Typography>
                <ToggleButtonGroup exclusive size="small" value={mes.provider} aria-label="MES transport"
                  onChange={(_, v) => v && setMesConfig({ provider: v })}>
                  <ToggleButton value="folder">Folder</ToggleButton>
                  <ToggleButton value="database">Database</ToggleButton>
                </ToggleButtonGroup>
                <Typography variant="caption" color="text.secondary">
                  {isDb ? "Inbound reads a status column of a customer table; outbound writes one row per run."
                        : "Each stage hands PASS/FAIL files to the next through a shared folder."}
                </Typography>
              </Stack>

              <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                <TextField select size="small" label="No MES record found" value={mes.on_missing} sx={{ width: 230 }}
                  onChange={(e) => setMesConfig({ on_missing: e.target.value })}
                  helperText="When the unit isn't known to MES">
                  <MenuItem value="block">Block the run</MenuItem>
                  <MenuItem value="allow">Allow the run</MenuItem>
                </TextField>
                {isDb && (
                  <TextField select size="small" label="MES unreachable / error" value={mes.on_error} sx={{ width: 230 }}
                    onChange={(e) => setMesConfig({ on_error: e.target.value })}
                    helperText="When the database can't be read">
                    <MenuItem value="block">Block the run</MenuItem>
                    <MenuItem value="allow">Allow the run</MenuItem>
                  </TextField>
                )}
              </Stack>

              {!isDb && (
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
              )}
            </Stack>
          </Section>

          {isDb && db && (
            <>
              <InboundCard saved={db.inbound ?? {}} enabled={mes.gate_enabled}
                onToggle={(v) => setMesConfig({ gate_enabled: v })}
                onSaved={(d) => { setDb(d); api.get("/mes/status").then(setMes).catch(() => {}); }} />
              <OutboundCard saved={db.outbound ?? {}} inboundConnection={db.inbound?.connection}
                fields={db.fields ?? []} enabled={mes.publish_enabled}
                onToggle={(v) => setMesConfig({ publish_enabled: v })}
                onSaved={(d) => { setDb(d); api.get("/mes/status").then(setMes).catch(() => {}); }} />
            </>
          )}
        </Stack>
      )}
    </Box>
  );
}
