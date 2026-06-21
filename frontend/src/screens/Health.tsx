import { PlayArrow } from "@mui/icons-material";
import {
  Alert, Box, Button, Chip, Grid, MenuItem, Paper, Stack, Table, TableBody, TableCell,
  TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageHeader, Section, StatusChip, type StatusKind } from "../components/ui";
import { useStream } from "../hooks/useStream";
import { MONO_STACK } from "../theme/theme";

interface Verdict { check_id: string; status: string; summary?: string; elapsed_ms?: number; instance_id?: string | null }
interface Suggestion { id: string; check_id: string; matched: boolean; issue_id?: string | null; summary?: string; remedy?: { text?: string } | null; references?: string[] }
interface Run { health_run_id: string; overall: string; counts: Record<string, number>; verdicts: Verdict[]; suggestions: Suggestion[]; summary: string; ts: number; trigger?: string }

const STATUS_KIND: Record<string, StatusKind> = {
  pass: "pass", fail: "fail", timeout: "fail", error: "fail",
  unavailable: "running", skipped: "idle",
};
const OVERALL_KIND: Record<string, StatusKind> = {
  healthy: "pass", degraded: "running", unhealthy: "fail", incomplete: "running",
};

export function Health() {
  const { can } = useAuth();
  const [checks, setChecks] = useState<any[]>([]);
  const [suites, setSuites] = useState<any[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [current, setCurrent] = useState<Run | null>(null);
  const [selected, setSelected] = useState<Run | null>(null);
  const [suite, setSuite] = useState("smoke");
  const [activeRun, setActiveRun] = useState<string | null>(null);
  const [live, setLive] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.get("/health/runs").then((r) => setRuns([...r].reverse())).catch((e) => setError(e.message));
    api.get("/health/current").then(setCurrent).catch(() => {});
  }, []);
  useEffect(() => {
    api.get("/health/checks").then(setChecks).catch((e) => setError(e.message));
    api.get("/health/suites").then(setSuites).catch(() => {});
    refresh();
  }, [refresh]);

  const { last } = useStream<any>(activeRun ? `/health/run/${activeRun}/stream` : null);
  useEffect(() => {
    if (!last) return;
    if (last.type === "check-completed") setLive((p) => ({ ...p, [last.check_id]: last.status }));
    if (last.type === "health-run-finished") {
      api.get(`/health/runs/${activeRun}`).then((r) => { setSelected(r); setCurrent(r); }).catch(() => {});
      setActiveRun(null); refresh();
    }
  }, [last]); // eslint-disable-line react-hooks/exhaustive-deps

  const runSuite = async () => {
    setError(null); setLive({});
    try { setActiveRun((await api.post("/health/run", { suite })).health_run_id); }
    catch (e: any) { setError(e.message); }
  };
  const runCheck = async (id: string) => {
    setError(null); setLive({});
    try { setActiveRun((await api.post(`/health/checks/${id}/run`, {})).health_run_id); }
    catch (e: any) { setError(e.message); }
  };

  const view = selected ?? current;
  const counts = view?.counts ?? {};

  return (
    <Box>
      <PageHeader
        title="System Health"
        subtitle="On-demand checks across web, bridge, and hardware"
        actions={can("HEALTH.RUN") && (
          <Stack direction="row" spacing={1}>
            <TextField select size="small" label="Suite" value={suite} onChange={(e) => setSuite(e.target.value)} sx={{ width: 130 }}>
              {suites.map((s) => <MenuItem key={s.name} value={s.name}>{s.name}</MenuItem>)}
            </TextField>
            <Button variant="contained" startIcon={<PlayArrow />} disabled={Boolean(activeRun)} onClick={runSuite}>
              {activeRun ? "Running…" : "Run"}
            </Button>
          </Stack>
        )}
      />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {view && (
        <Grid container spacing={2} sx={{ mb: 2 }}>
          <Grid item xs={12} sm={4}>
            <Paper sx={{ p: 2 }}>
              <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: "0.06em" }}>Overall</Typography>
              <Box sx={{ mt: 0.5 }}><StatusChip label={view.overall} kind={OVERALL_KIND[view.overall] ?? "idle"} size="medium" /></Box>
            </Paper>
          </Grid>
          <Grid item xs={12} sm={8}>
            <Paper sx={{ p: 2 }}>
              <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: "0.06em" }}>Counts</Typography>
              <Stack direction="row" spacing={1} sx={{ mt: 0.5 }} flexWrap="wrap" useFlexGap>
                {Object.entries(counts).map(([k, n]) => <Chip key={k} size="small" label={`${k}: ${n}`} />)}
                {Object.keys(counts).length === 0 && <Typography variant="body2" color="text.secondary">—</Typography>}
              </Stack>
            </Paper>
          </Grid>
        </Grid>
      )}

      <Stack direction={{ xs: "column", lg: "row" }} spacing={2}>
        <Box sx={{ flex: 2, minWidth: 0 }}>
          <Section title={selected ? `Run ${selected.health_run_id.slice(0, 8)}` : activeRun ? "Live run" : "Latest run"} bodyPad={0} sx={{ mb: 2 }}>
            {(view?.verdicts?.length || activeRun) ? (
              <Table>
                <TableHead><TableRow><TableCell>Check</TableCell><TableCell>Status</TableCell><TableCell>Summary</TableCell></TableRow></TableHead>
                <TableBody>
                  {(view?.verdicts ?? checks.map((c) => ({ check_id: c.id, status: live[c.id] || "pending", summary: "" }))).map((v: Verdict) => {
                    const st = activeRun ? (live[v.check_id] || "pending") : v.status;
                    return (
                      <TableRow key={v.check_id}>
                        <TableCell sx={{ fontFamily: MONO_STACK }}>{v.check_id}</TableCell>
                        <TableCell>{st === "pending" ? <Chip size="small" label="pending" /> : <StatusChip label={st} kind={STATUS_KIND[st] ?? "idle"} />}</TableCell>
                        <TableCell sx={{ color: "text.secondary" }}>{v.summary}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            ) : <EmptyState message="No run yet. Press Run." />}
          </Section>

          {view?.suggestions?.length ? (
            <Section title="Suggestions">
              <Stack spacing={1.5}>
                {view.suggestions.map((s) => (
                  <Alert key={s.id} severity={s.matched ? "warning" : "info"}>
                    <Typography variant="subtitle2">{s.check_id} — {s.matched ? s.summary : "unknown signature (no catalog match yet)"}</Typography>
                    {s.remedy?.text && <Typography variant="body2" sx={{ mt: 0.5 }}>{s.remedy.text}</Typography>}
                    {s.references?.length ? <Typography variant="caption" color="text.secondary">refs: {s.references.join(", ")}</Typography> : null}
                  </Alert>
                ))}
              </Stack>
            </Section>
          ) : null}
        </Box>

        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Section title="Checks" bodyPad={0} sx={{ mb: 2 }}>
            <Table size="small">
              <TableBody>
                {checks.map((c) => (
                  <TableRow key={c.id} hover>
                    <TableCell sx={{ fontFamily: MONO_STACK }}>
                      {c.id}{c.disruptive && <Chip size="small" label="disruptive" color="warning" sx={{ ml: 1, height: 16, fontSize: 10 }} />}
                      {!c.reachable && <Chip size="small" label="unreachable" sx={{ ml: 1, height: 16, fontSize: 10 }} />}
                    </TableCell>
                    <TableCell align="right">
                      {can("HEALTH.RUN") && <Button size="small" disabled={Boolean(activeRun)} onClick={() => runCheck(c.id)}>Run</Button>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Section>

          <Section title="History" bodyPad={0}>
            {runs.length === 0 ? <EmptyState message="No runs." /> : (
              <Table size="small">
                <TableBody>
                  {runs.slice(0, 15).map((r) => (
                    <TableRow key={r.health_run_id} hover sx={{ cursor: "pointer" }} onClick={() => setSelected(r)}>
                      <TableCell><StatusChip label={r.overall} kind={OVERALL_KIND[r.overall] ?? "idle"} /></TableCell>
                      <TableCell sx={{ color: "text.secondary" }}>{new Date(r.ts * 1000).toLocaleString()}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Section>
        </Box>
      </Stack>
    </Box>
  );
}
