import {
  Box, Button, Chip, Dialog, DialogContent, DialogTitle, Grid, MenuItem, Paper, Stack,
  Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";

interface Analytics {
  total: number; passed: number; failed: number; yield: number;
  by_recipe: Record<string, { total: number; passed: number; failed: number }>;
  by_result: Record<string, number>;
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <Paper sx={{ p: 2, textAlign: "center" }}>
      <Typography variant="h4">{value}</Typography>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
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
      setRows((await api.get(`/reports?${q.toString()}`)).items);
    } catch (e: any) { setError(e.message); }
  }, [result, recipe]);

  useEffect(() => { load(); }, [load]);

  return (
    <Stack spacing={2}>
      <Typography variant="h5">Reports</Typography>
      {error && <Typography color="error">{error}</Typography>}

      {analytics && (
        <Grid container spacing={2}>
          <Grid item xs={3}><Stat label="runs" value={analytics.total} /></Grid>
          <Grid item xs={3}><Stat label="passed" value={analytics.passed} /></Grid>
          <Grid item xs={3}><Stat label="failed" value={analytics.failed} /></Grid>
          <Grid item xs={3}><Stat label="yield %" value={analytics.yield} /></Grid>
        </Grid>
      )}

      {analytics && Object.keys(analytics.by_recipe).length > 0 && (
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle1">By recipe</Typography>
          <Table size="small">
            <TableHead><TableRow>
              <TableCell>Recipe</TableCell><TableCell>Total</TableCell>
              <TableCell>Passed</TableCell><TableCell>Failed</TableCell>
            </TableRow></TableHead>
            <TableBody>
              {Object.entries(analytics.by_recipe).map(([rid, s]) => (
                <TableRow key={rid}>
                  <TableCell>{rid}</TableCell><TableCell>{s.total}</TableCell>
                  <TableCell>{s.passed}</TableCell><TableCell>{s.failed}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}

      <Stack direction="row" spacing={2} alignItems="center">
        <TextField select size="small" label="result" value={result} sx={{ minWidth: 140 }}
          onChange={(e) => setResult(e.target.value)}>
          <MenuItem value="">all</MenuItem>
          <MenuItem value="PASS">PASS</MenuItem>
          <MenuItem value="FAIL">FAIL</MenuItem>
        </TextField>
        <TextField size="small" label="recipe_id" value={recipe} onChange={(e) => setRecipe(e.target.value)} />
      </Stack>

      <Paper>
        <Table size="small">
          <TableHead><TableRow>
            <TableCell>Run</TableCell><TableCell>Recipe</TableCell>
            <TableCell>Result</TableCell><TableCell>Finished</TableCell>
          </TableRow></TableHead>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.run_id} hover sx={{ cursor: "pointer" }} onClick={() => setOpen(r)}>
                <TableCell>{r.run_id}</TableCell>
                <TableCell>{r.recipe_id}</TableCell>
                <TableCell><Chip size="small" label={r.result}
                  color={String(r.result).startsWith("PASS") ? "success" : "error"} /></TableCell>
                <TableCell>{r.finished_ts ? new Date(r.finished_ts * 1000).toLocaleString() : "-"}</TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && <TableRow><TableCell colSpan={4}>No reports.</TableCell></TableRow>}
          </TableBody>
        </Table>
      </Paper>

      <Dialog open={Boolean(open)} onClose={() => setOpen(null)} maxWidth="md" fullWidth>
        {open && (
          <>
            <DialogTitle>Run {open.run_id} — {open.result}</DialogTitle>
            <DialogContent>
              <Stack spacing={1}>
                <Typography variant="caption">recipe {open.recipe_id} v{open.recipe_version}</Typography>
                {can("REPORT.EXPORT") && (
                  <Stack direction="row" spacing={1}>
                    <Button size="small" onClick={() => downloadReport(open.run_id, "json")}>Export JSON</Button>
                    <Button size="small" onClick={() => downloadReport(open.run_id, "csv")}>Export CSV</Button>
                  </Stack>
                )}
                <Typography variant="subtitle2">Steps</Typography>
                <Box component="pre" sx={{ overflow: "auto", fontSize: 12 }}>
                  {JSON.stringify(open.steps, null, 2)}
                </Box>
              </Stack>
            </DialogContent>
          </>
        )}
      </Dialog>
    </Stack>
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
