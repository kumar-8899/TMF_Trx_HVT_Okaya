/** MES interlock config — moved here from Settings into the Config menu. */
import {
  Alert, Box, Chip, FormControlLabel, Stack, Switch, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { EmptyState, PageHeader, Section } from "../../components/ui";
import { MONO_STACK } from "../../theme/theme";

interface MesStatus {
  stage: string; provider: string; gate_enabled: boolean; publish_enabled: boolean;
  on_missing: string; provider_detail: Record<string, any>;
}

export function ConfigMes() {
  const [mes, setMes] = useState<MesStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api.get("/mes/status").then((m) => { setMes(m); setLoaded(true); }).catch(() => setLoaded(true));
  }, []);

  const setMesConfig = async (patch: Partial<MesStatus>) => {
    setError(null);
    try { setMes(await api.put("/mes/config", patch)); }
    catch (e: any) { setError(e.message); }
  };

  return (
    <Box>
      <PageHeader title="MES interlock" subtitle="Cross-station gate & publish" />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {!mes ? (loaded && <Section><EmptyState message="MES module is not enabled on this station." /></Section>) : (
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
    </Box>
  );
}
