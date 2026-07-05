import { Download, Search, TableViewOutlined } from "@mui/icons-material";
import {
  Alert, Box, Button, Dialog, DialogContent, DialogTitle, Grid, InputAdornment, LinearProgress,
  MenuItem, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageHeader, Section, StatusChip, statusKind } from "../components/ui";
import { ResultsTable } from "../components/testing/ResultsTable";
import { MONO_STACK } from "../theme/theme";

interface Analytics {
  total: number; passed: number; failed: number; yield: number;
  by_recipe?: Record<string, { total: number; passed: number; failed: number }>;
  by_result?: Record<string, number>;
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

const FIXED_LABEL: Record<string, string> = {
  serial_no: "Serial No", model: "Model", recipe_id: "Recipe", result: "Result",
  business_day: "Business day", shift_label: "Shift", finished_ts: "Finished", cycle_s: "Cycle (s)",
};
const PAGE_SIZES = [25, 50, 100, 200];

export function Reports() {
  const { can } = useAuth();
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [models, setModels] = useState<string[]>([]);
  // filters
  const [result, setResult] = useState("");
  const [serial, setSerial] = useState("");
  const [model, setModel] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [pageSize, setPageSize] = useState(50);
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<any | null>(null);
  const [full, setFull] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [configured, setConfigured] = useState(true);

  const qs = useCallback(() => {
    const q = new URLSearchParams();
    if (result) q.set("result", result);
    if (serial) q.set("serial", serial);
    if (model) q.set("model", model);
    if (dateFrom) q.set("date_from", dateFrom);
    if (dateTo) q.set("date_to", dateTo);
    return q;
  }, [result, serial, model, dateFrom, dateTo]);

  const load = useCallback(async () => {
    setError(null);
    try {
      setAnalytics(await api.get("/reports/analytics"));
      const q = qs();
      q.set("limit", String(pageSize));
      if (offset) q.set("cursor", String(offset));
      const resp = await api.get(`/reports?${q.toString()}`);   // store returns newest-first
      setRows(resp.items || []);
      setTotal(resp.total || 0);
      setConfigured(resp.configured !== false);
    } catch (e: any) { setError(e.message); }
  }, [qs, pageSize, offset]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.get("/reports/models").then(setModels).catch(() => {}); }, []);
  useEffect(() => { setOffset(0); }, [result, serial, model, dateFrom, dateTo, pageSize]);   // filters reset paging

  const openFull = async () => {
    setError(null);
    try { setFull(await api.get(`/reports/full?${qs().toString()}`)); }
    catch (e: any) { setError(e.message); }
  };
  const exportFull = () => downloadUrl(`/reports/full/export?${qs().toString()}`, "reports-full.csv");

  return (
    <Box>
      <PageHeader title="Reports" subtitle="Run outcomes, yield, and analytics" />
      {error && <Typography color="error" sx={{ mb: 2 }}>{error}</Typography>}
      {!configured && (
        <Alert severity="info" sx={{ mb: 2 }}>Report database not configured — set it in <b>Settings → Report database</b>. New reports are queued locally until then.</Alert>
      )}

      <Stack spacing={2}>
        {analytics && (
          <Grid container spacing={2}>
            <Grid item xs={6} sm={3}><Stat label="runs" value={analytics.total} /></Grid>
            <Grid item xs={6} sm={3}><Stat label="passed" value={analytics.passed} kind="pass" /></Grid>
            <Grid item xs={6} sm={3}><Stat label="failed" value={analytics.failed} kind="fail" /></Grid>
            <Grid item xs={6} sm={3}><Stat label="yield %" value={analytics.yield} kind="info" /></Grid>
          </Grid>
        )}

        {analytics?.by_recipe && Object.keys(analytics.by_recipe).length > 0 && (
          <Section title="By recipe">
            <Table>
              <TableHead><TableRow>
                <TableCell>Recipe</TableCell><TableCell align="right">Total</TableCell>
                <TableCell align="right">Passed</TableCell><TableCell align="right">Failed</TableCell>
                <TableCell sx={{ width: 200 }}>Yield</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {Object.entries(analytics.by_recipe ?? {}).map(([rid, s]) => {
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

        <Section title="Run reports" bodyPad={0}
          actions={<Button size="small" variant="outlined" startIcon={<TableViewOutlined />} onClick={openFull}>Full view</Button>}>
          <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap sx={{ p: 2, pb: 1.5 }}>
            <TextField size="small" label="Serial No" value={serial} onChange={(e) => setSerial(e.target.value)}
              InputProps={{ startAdornment: <InputAdornment position="start"><Search fontSize="small" /></InputAdornment> }} sx={{ width: 200 }} />
            <TextField size="small" select label="Model" value={model} onChange={(e) => setModel(e.target.value)} sx={{ minWidth: 150 }}>
              <MenuItem value="">All models</MenuItem>
              {models.map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}
            </TextField>
            <TextField size="small" select label="Result" value={result} sx={{ minWidth: 120 }}
              onChange={(e) => setResult(e.target.value)}>
              <MenuItem value="">All</MenuItem>
              <MenuItem value="PASS">PASS</MenuItem>
              <MenuItem value="FAIL">FAIL</MenuItem>
              <MenuItem value="ABORTED">ABORTED</MenuItem>
            </TextField>
            <TextField size="small" type="date" label="From (business day)" value={dateFrom} sx={{ width: 180 }}
              InputLabelProps={{ shrink: true }} onChange={(e) => setDateFrom(e.target.value)} />
            <TextField size="small" type="date" label="To" value={dateTo} sx={{ width: 160 }}
              InputLabelProps={{ shrink: true }} onChange={(e) => setDateTo(e.target.value)} />
          </Stack>

          {rows.length === 0 ? (
            <EmptyState message="No reports." />
          ) : (
            <Table>
              <TableHead><TableRow>
                <TableCell>Serial No</TableCell><TableCell>Model</TableCell><TableCell>Recipe</TableCell>
                <TableCell>Result</TableCell><TableCell align="right">Cycle (s)</TableCell><TableCell>Finished</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.run_id} hover sx={{ cursor: "pointer" }} onClick={() => setOpen(r)}>
                    <TableCell sx={{ fontFamily: MONO_STACK }}>{r.serial_no || r.run_id}</TableCell>
                    <TableCell>{r.model || "—"}</TableCell>
                    <TableCell sx={{ fontFamily: MONO_STACK }}>{r.recipe_id || "—"}</TableCell>
                    <TableCell><StatusChip label={r.result} kind={statusKind(r.result)} /></TableCell>
                    <TableCell align="right" sx={{ fontFamily: MONO_STACK }}>{r.cycle_s ?? "—"}</TableCell>
                    <TableCell sx={{ color: "text.secondary" }}>
                      {r.finished_ts ? new Date(r.finished_ts * 1000).toLocaleString() : "-"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {/* pagination */}
          <Stack direction="row" spacing={2} alignItems="center" justifyContent="flex-end" sx={{ p: 1.5 }}>
            <TextField size="small" select label="Rows" value={pageSize} sx={{ width: 90 }}
              onChange={(e) => setPageSize(Number(e.target.value))}>
              {PAGE_SIZES.map((n) => <MenuItem key={n} value={n}>{n}</MenuItem>)}
            </TextField>
            <Typography variant="body2" color="text.secondary">
              {total === 0 ? "0" : `${offset + 1}–${Math.min(offset + rows.length, total)} of ${total}`}
            </Typography>
            <Button size="small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Prev</Button>
            <Button size="small" disabled={offset + rows.length >= total} onClick={() => setOffset(offset + pageSize)}>Next</Button>
          </Stack>
        </Section>
      </Stack>

      {/* Full view — flattened test-data matrix (one row per run, a column per test parameter) */}
      <Dialog open={Boolean(full)} onClose={() => setFull(null)} maxWidth={false} fullWidth
        PaperProps={{ sx: { width: "95vw", maxWidth: "95vw", height: "90vh" } }}>
        <DialogTitle>
          <Stack direction="row" alignItems="center" justifyContent="space-between">
            <span>Full view — {full?.rows?.length ?? 0} run(s){full?.truncated ? " (capped)" : ""}</span>
            <Stack direction="row" spacing={1}>
              {can("REPORT.EXPORT") && <Button size="small" variant="contained" startIcon={<Download />} onClick={exportFull}>Export CSV (all filtered)</Button>}
              <Button size="small" onClick={() => setFull(null)}>Close</Button>
            </Stack>
          </Stack>
        </DialogTitle>
        <DialogContent sx={{ p: 0 }}>
          {full && (
            <Box sx={{ overflow: "auto", height: "100%" }}>
              <Table size="small" stickyHeader>
                <TableHead><TableRow>
                  {[...full.fixed, ...full.tests].map((c: string) => (
                    <TableCell key={c} sx={{ whiteSpace: "nowrap", fontWeight: 700 }}>{FIXED_LABEL[c] || c}</TableCell>
                  ))}
                </TableRow></TableHead>
                <TableBody>
                  {full.rows.map((r: any) => (
                    <TableRow key={r.run_id} hover>
                      {[...full.fixed, ...full.tests].map((c: string) => (
                        <TableCell key={c} sx={{ whiteSpace: "nowrap", fontFamily: c === "result" ? undefined : MONO_STACK }}>
                          {c === "finished_ts" ? (r[c] ? new Date(r[c] * 1000).toLocaleString() : "—")
                            : c === "result" ? <StatusChip label={r[c]} kind={statusKind(r[c])} />
                            : (r[c] && typeof r[c] === "object") ? (
                              <Box>
                                <span style={{ fontWeight: 600 }}>{r[c].measured ?? "—"}{r[c].unit ? ` ${r[c].unit}` : ""}</span>
                                <Typography variant="caption" sx={{ display: "block", color: statusKind(r[c].result) === "fail" ? "error.main" : "text.secondary" }}>
                                  exp {r[c].expected ?? "—"} · {r[c].result ?? "—"}{r[c].cycle_s != null ? ` · ${r[c].cycle_s}s` : ""}
                                </Typography>
                              </Box>
                            ) : (r[c] ?? "—")}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(open)} onClose={() => setOpen(null)} maxWidth="md" fullWidth>
        {open && (
          <>
            <DialogTitle>
              <Stack direction="row" spacing={1.5} alignItems="center">
                <span style={{ fontFamily: MONO_STACK }}>{open.serial_no || open.run_id}</span>
                <StatusChip label={open.result} kind={statusKind(open.result)} />
              </Stack>
            </DialogTitle>
            <DialogContent>
              <Stack spacing={1.5}>
                <Typography variant="caption" color="text.secondary">
                  recipe {open.recipe_id || "—"}{open.recipe_version ? ` v${open.recipe_version}` : ""} · run {open.run_id}
                </Typography>
                {can("REPORT.EXPORT") && (
                  <Stack direction="row" spacing={1}>
                    <Button size="small" variant="outlined" startIcon={<Download />}
                      onClick={() => downloadReport(open.run_id, "json")}>Export JSON</Button>
                    <Button size="small" variant="outlined" startIcon={<Download />}
                      onClick={() => downloadReport(open.run_id, "csv")}>Export CSV</Button>
                  </Stack>
                )}
                <ResultsTable rows={open.rows || []} />
              </Stack>
            </DialogContent>
          </>
        )}
      </Dialog>
    </Box>
  );
}

const downloadReport = (runId: string, fmt: string) =>
  downloadUrl(`/reports/${runId}/export?format=${fmt}`, `report-${runId}.${fmt}`);

async function downloadUrl(path: string, filename: string): Promise<void> {
  const tok = localStorage.getItem("tmf.token");
  const res = await fetch(path, { headers: tok ? { Authorization: `Bearer ${tok}` } : {} });
  if (!res.ok) return;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}
