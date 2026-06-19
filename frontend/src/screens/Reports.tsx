import { Download } from "@mui/icons-material";
import {
  Box, Button, Dialog, DialogContent, DialogTitle, Grid, LinearProgress, MenuItem,
  Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageHeader, Section, StatusChip, statusKind } from "../components/ui";
import { MONO_STACK } from "../theme/theme";

interface Analytics {
  total: number; passed: number; failed: number; yield: number;
  by_recipe: Record<string, { total: number; passed: number; failed: number }>;
  by_result: Record<string, number>;
}

const STAT_COLOR = { pass: "success.main", fail: "error.main", info: "info.main" } as const;

function Stat({ label, value, kind }: { label: string; value: number | string; kind?: "pass" | "fail" | "info" }) {
  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {label}
      </Typography>
      <Typography variant="h4" sx={{ mt: 0.5, color: kind ? STAT_COLOR[kind] : "text.primary" }}>
        {value}
      </Typography>
    </Paper>
  );
}

export function Reports() {
  const { can } = useAuth();
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [result, setResult] = useState("");
  const [recipe, setRecipe] = useState("");
  const [open, setOpen] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setAnalytics(await api.get("/reports/analytics"));
      const q = new URLSearchParams();
      if (result) q.set("result", result);
      if (recipe) q.set("recipe_id", recipe);
      // newest first (the API returns oldest-first)
      setRows([...(await api.get(`/reports?${q.toString()}`)).items].reverse());
    } catch (e: any) { setError(e.message); }
  }, [result, recipe]);

  useEffect(() => { load(); }, [load]);

  return (
    <Box>
      <PageHeader title="Reports" subtitle="Run outcomes, yield, and analytics" />
      {error && <Typography color="error" sx={{ mb: 2 }}>{error}</Typography>}

      <Stack spacing={2}>
        {analytics && (
          <Grid container spacing={2}>
            <Grid item xs={6} sm={3}><Stat label="runs" value={analytics.total} /></Grid>
            <Grid item xs={6} sm={3}><Stat label="passed" value={analytics.passed} kind="pass" /></Grid>
            <Grid item xs={6} sm={3}><Stat label="failed" value={analytics.failed} kind="fail" /></Grid>
            <Grid item xs={6} sm={3}><Stat label="yield %" value={analytics.yield} kind="info" /></Grid>
          </Grid>
        )}

        {analytics && Object.keys(analytics.by_recipe).length > 0 && (
          <Section title="By recipe">
            <Table>
              <TableHead><TableRow>
                <TableCell>Recipe</TableCell><TableCell align="right">Total</TableCell>
                <TableCell align="right">Passed</TableCell><TableCell align="right">Failed</TableCell>
                <TableCell sx={{ width: 200 }}>Yield</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {Object.entries(analytics.by_recipe).map(([rid, s]) => {
                  const y = s.total ? (s.passed / s.total) * 100 : 0;
                  return (
                    <TableRow key={rid}>
                      <TableCell sx={{ fontFamily: MONO_STACK }}>{rid}</TableCell>
                      <TableCell align="right">{s.total}</TableCell>
                      <TableCell align="right">{s.passed}</TableCell>
                      <TableCell align="right">{s.failed}</TableCell>
                      <TableCell>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <LinearProgress variant="determinate" value={y}
                            color={y >= 90 ? "success" : y >= 70 ? "warning" : "error"}
                            sx={{ flex: 1, height: 6, borderRadius: 3 }} />
                          <Typography variant="caption" sx={{ fontFamily: MONO_STACK, minWidth: 36 }}>
                            {y.toFixed(0)}%
                          </Typography>
                        </Stack>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </Section>
        )}

        <Section title="Run reports" bodyPad={0}>
          <Stack direction="row" spacing={2} alignItems="center" sx={{ p: 2, pb: 1.5 }}>
            <TextField select label="result" value={result} sx={{ minWidth: 140 }}
              onChange={(e) => setResult(e.target.value)}>
              <MenuItem value="">all</MenuItem>
              <MenuItem value="PASS">PASS</MenuItem>
              <MenuItem value="FAIL">FAIL</MenuItem>
            </TextField>
            <TextField label="recipe_id" value={recipe} onChange={(e) => setRecipe(e.target.value)} />
          </Stack>

          {rows.length === 0 ? (
            <EmptyState message="No reports." />
          ) : (
            <Table>
              <TableHead><TableRow>
                <TableCell>Run</TableCell><TableCell>Recipe</TableCell>
                <TableCell>Result</TableCell><TableCell>Finished</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.run_id} hover sx={{ cursor: "pointer" }} onClick={() => setOpen(r)}>
                    <TableCell sx={{ fontFamily: MONO_STACK }}>{r.run_id}</TableCell>
                    <TableCell sx={{ fontFamily: MONO_STACK }}>{r.recipe_id}</TableCell>
                    <TableCell><StatusChip label={r.result} kind={statusKind(r.result)} /></TableCell>
                    <TableCell sx={{ color: "text.secondary" }}>
                      {r.finished_ts ? new Date(r.finished_ts * 1000).toLocaleString() : "-"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Section>
      </Stack>

      <Dialog open={Boolean(open)} onClose={() => setOpen(null)} maxWidth="md" fullWidth>
        {open && (
          <>
            <DialogTitle>
              <Stack direction="row" spacing={1.5} alignItems="center">
                <span style={{ fontFamily: MONO_STACK }}>Run {open.run_id}</span>
                <StatusChip label={open.result} kind={statusKind(open.result)} />
              </Stack>
            </DialogTitle>
            <DialogContent>
              <Stack spacing={1.5}>
                <Typography variant="caption" color="text.secondary">
                  recipe {open.recipe_id} v{open.recipe_version}
                </Typography>
                {can("REPORT.EXPORT") && (
                  <Stack direction="row" spacing={1}>
                    <Button size="small" variant="outlined" startIcon={<Download />}
                      onClick={() => downloadReport(open.run_id, "json")}>Export JSON</Button>
                    <Button size="small" variant="outlined" startIcon={<Download />}
                      onClick={() => downloadReport(open.run_id, "csv")}>Export CSV</Button>
                  </Stack>
                )}
                <Typography variant="subtitle2">Steps</Typography>
                <Box component="pre" sx={{
                  overflow: "auto", fontSize: 12, fontFamily: MONO_STACK, p: 1.5, borderRadius: 1, m: 0,
                  bgcolor: (t) => (t.palette.mode === "dark" ? "rgba(255,255,255,0.04)" : "rgba(2,6,23,0.04)"),
                }}>
                  {JSON.stringify(open.steps, null, 2)}
                </Box>
              </Stack>
            </DialogContent>
          </>
        )}
      </Dialog>
    </Box>
  );
}

async function downloadReport(runId: string, fmt: string): Promise<void> {
  const tok = localStorage.getItem("tmf.token");
  const res = await fetch(`/reports/${runId}/export?format=${fmt}`,
    { headers: tok ? { Authorization: `Bearer ${tok}` } : {} });
  if (!res.ok) return;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = `report-${runId}.${fmt}`; a.click();
  URL.revokeObjectURL(url);
}
