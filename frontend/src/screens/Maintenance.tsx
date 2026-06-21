import { Build, PlayArrow, Stop } from "@mui/icons-material";
import {
  Alert, Box, Button, Grid, MenuItem, Stack, TextField, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { EmptyState, PageHeader, Section, StatusChip } from "../components/ui";
import { LiveVariablesPanel } from "../components/testing/LiveVariablesPanel";
import { useValues } from "../hooks/useValues";
import { MONO_STACK } from "../theme/theme";

/** Maintenance Console — hands-on hardware operation, composed from existing
 * contracts (Variable Engine writes, health one-check, LabVIEW maintenance mode).
 * The hard rule: commands (writes, disruptive checks) only when maintenance == on;
 * otherwise read-only (HEALTH_CHECK.md §9). No new backend module. */
export function Maintenance() {
  const [maint, setMaint] = useState<{ state: string; by?: string; reason?: string } | null>(null);
  const [reason, setReason] = useState("");
  const [checks, setChecks] = useState<any[]>([]);
  const [pickCheck, setPickCheck] = useState("");
  const [name, setName] = useState("vbus_main");
  const [value, setValue] = useState("");
  const [result, setResult] = useState("");
  const [error, setError] = useState<string | null>(null);
  const values = useValues("/instruments/values/ws");

  const refresh = () => api.get("/health/maintenance").then(setMaint).catch(() => setMaint(null));
  useEffect(() => {
    refresh();
    api.get("/health/checks").then(setChecks).catch(() => {});
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, []);

  const on = maint?.state === "on";

  const enter = async () => { setError(null); try { setMaint((await api.post("/health/maintenance/enter", { reason })).state ? await api.get("/health/maintenance") : maint); refresh(); } catch (e: any) { setError(e.message); } };
  const exit = async () => { setError(null); try { await api.post("/health/maintenance/exit", {}); refresh(); } catch (e: any) { setError(e.message); } };

  const read = async () => { setError(null); try { setResult(JSON.stringify(await api.get(`/variables/${name}/value`))); } catch (e: any) { setError(e.message); } };
  const write = async (v: number) => { setError(null); try { await api.put(`/variables/${name}/value`, { value: v }); setResult(`wrote ${v} → ${name}`); } catch (e: any) { setError(e.message); } };
  const runCheck = async () => { setError(null); try { setResult(`started ${(await api.post(`/health/checks/${pickCheck}/run`, {})).health_run_id}`); } catch (e: any) { setError(e.message); } };

  return (
    <Box>
      <PageHeader title="Maintenance Console" subtitle="Hands-on hardware operation"
        actions={
          on
            ? <Button variant="outlined" color="warning" startIcon={<Stop />} onClick={exit}>Exit maintenance</Button>
            : <Stack direction="row" spacing={1}>
                <TextField size="small" label="reason" value={reason} onChange={(e) => setReason(e.target.value)} />
                <Button variant="contained" startIcon={<Build />} onClick={enter}>Enter maintenance</Button>
              </Stack>
        } />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Section sx={{ mb: 2 }}>
        <Stack direction="row" spacing={3} alignItems="center" flexWrap="wrap" useFlexGap>
          <Box>
            <Typography variant="caption" color="text.secondary" display="block">MAINTENANCE</Typography>
            <StatusChip label={maint?.state ?? "—"} kind={on ? "running" : "idle"} />
          </Box>
          {maint?.by && <Box><Typography variant="caption" color="text.secondary" display="block">BY</Typography><Typography>{maint.by}</Typography></Box>}
          {!on && <Alert severity="info" sx={{ py: 0 }}>Read-only — enter maintenance to command hardware.</Alert>}
        </Stack>
      </Section>

      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Section title="Variables" subtitle="read anytime · write only in maintenance">
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <TextField size="small" label="variable" value={name} onChange={(e) => setName(e.target.value)} sx={{ width: 180 }} />
              <Button variant="outlined" onClick={read}>Read</Button>
              <TextField size="small" label="value" value={value} onChange={(e) => setValue(e.target.value)} sx={{ width: 110 }} disabled={!on} />
              <Button variant="contained" disabled={!on || value === ""} onClick={() => write(Number(value))}>Write</Button>
              <Button size="small" variant="outlined" color="inherit" disabled={!on} onClick={() => write(0)}>0</Button>
              <Button size="small" variant="outlined" color="inherit" disabled={!on} onClick={() => write(1)}>1</Button>
            </Stack>
            {result && <Typography variant="body2" sx={{ mt: 1.5, fontFamily: MONO_STACK }}>{result}</Typography>}
          </Section>
        </Grid>
        <Grid item xs={12} md={6}>
          <Section title="Run a health check">
            <Stack direction="row" spacing={1} alignItems="center">
              <TextField select size="small" label="check" value={pickCheck} onChange={(e) => setPickCheck(e.target.value)} sx={{ flex: 1 }}>
                {checks.map((c) => <MenuItem key={c.id} value={c.id}>{c.id}{c.disruptive ? " (disruptive)" : ""}</MenuItem>)}
              </TextField>
              <Button variant="contained" startIcon={<PlayArrow />} disabled={!pickCheck} onClick={runCheck}>Run</Button>
            </Stack>
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
              Disruptive checks run only in maintenance mode.
            </Typography>
          </Section>
        </Grid>
        <Grid item xs={12}>
          {Object.keys(values).length ? <LiveVariablesPanel variables={[]} values={values} /> : <Section title="Live values"><EmptyState message="No live values streaming." /></Section>}
        </Grid>
      </Grid>
    </Box>
  );
}
