import { PlayArrow, QrCodeScanner, Stop } from "@mui/icons-material";
import {
  Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack,
  Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, TextField, Typography,
} from "@mui/material";
import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageHeader, Section, StatusChip, StatusDot, statusKind } from "../components/ui";
import { useStream } from "../hooks/useStream";
import { MONO_STACK } from "../theme/theme";

interface EventEnvelope { type: string; ts: number; payload?: Record<string, any> }
interface ResultRow {
  serial_no?: number; test_name?: string; expected?: any; measured?: any;
  result?: string; cycle_time_ms?: number;
}

function fmtTime(ts: number) {
  if (!ts) return "";
  return new Date(ts * (ts > 1e12 ? 1 : 1000)).toLocaleTimeString();
}

export function Runs() {
  const { can } = useAuth();
  const [runs, setRuns] = useState<any[]>([]);
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [error, setError] = useState<string | null>(null);

  // active run + live results
  const [runId, setRunId] = useState<string | null>(null);
  const [recipeId, setRecipeId] = useState<string>("");
  const [runStatus, setRunStatus] = useState<string>("");
  const [results, setResults] = useState<ResultRow[]>([]);

  // start dialog
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"barcode" | "recipe">("barcode");
  const [barcode, setBarcode] = useState("");
  const [pickRecipe, setPickRecipe] = useState("");
  const [recipes, setRecipes] = useState<{ recipe_id: string; name: string }[]>([]);
  const [prefixLen, setPrefixLen] = useState(3);

  const { last, status } = useStream<EventEnvelope>("/ws/station");

  const refresh = () => api.get("/runs").then(setRuns).catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
    api.get("/runs/acquisition").then((a) => {
      setMode(a.default_mode === "recipe" ? "recipe" : "barcode");
      setPrefixLen(a.barcode?.length ?? 3);
    }).catch(() => {});
    api.get("/recipes").then((rs) => setRecipes(rs)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!last) return;
    setEvents((prev) => [last, ...prev].slice(0, 50));
    const t = String(last.type);
    const body = last.payload ?? {};
    if (t.startsWith("run-")) refresh();
    if (runId && body.run_id === runId) {
      if (t === "test-result") setResults((prev) => [...prev, body as ResultRow]);
      else if (t === "run-started") setRunStatus("running");
      else if (t === "run-finished") setRunStatus(body.result || "finished");
      else if (t === "run-aborted") setRunStatus("ABORTED");
    }
  }, [last]); // eslint-disable-line react-hooks/exhaustive-deps

  const resolvedPreview = barcode.trim().slice(0, prefixLen);

  const startRun = async () => {
    setError(null);
    try {
      const body = mode === "barcode" ? { barcode } : { recipe_id: pickRecipe };
      const res = await api.post("/runs/start", body);
      setRunId(res.run_id); setRecipeId(res.recipe_id); setRunStatus("running"); setResults([]);
      setOpen(false); setBarcode(""); setPickRecipe("");
      refresh();
    } catch (e: any) { setError(e.message); }
  };

  const abort = async () => {
    setError(null);
    try { await api.post("/runs/abort", {}); } catch (e: any) { setError(e.message); }
  };

  const openRun = async (id: string) => {
    setError(null);
    try {
      const rec = await api.get(`/runs/${id}`);
      const d = rec.data ?? {};
      setRunId(id); setRecipeId(d.recipe_id || ""); setResults(d.results || []);
      setRunStatus(d.result || d.status || "");
    } catch (e: any) { setError(e.message); }
  };

  const passN = useMemo(() => results.filter((r) => String(r.result).toUpperCase() === "PASS").length, [results]);

  return (
    <Box>
      <PageHeader
        title="Runs"
        subtitle="Start and monitor test executions on the station"
        actions={
          <>
            <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mr: 1 }}>
              <StatusDot kind={status === "open" ? "pass" : "idle"} />
              <Typography variant="caption" color="text.secondary">{status === "open" ? "live" : "offline"}</Typography>
            </Stack>
            {can("TEST.RUN") && <Button variant="contained" startIcon={<PlayArrow />} onClick={() => setOpen(true)}>Start test</Button>}
            {can("TEST.RUN") && <Button variant="outlined" color="error" startIcon={<Stop />} onClick={abort}>Abort</Button>}
          </>
        }
      />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {/* Active / selected run banner */}
      {runId && (
        <Section sx={{ mb: 2 }}>
          <Stack direction="row" spacing={3} alignItems="center" flexWrap="wrap" useFlexGap>
            <Box>
              <Typography variant="caption" color="text.secondary">RUN</Typography>
              <Typography sx={{ fontFamily: MONO_STACK, fontWeight: 600 }}>{runId}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">RECIPE</Typography>
              <Typography sx={{ fontFamily: MONO_STACK }}>{recipeId || "—"}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" display="block">STATUS</Typography>
              <StatusChip label={runStatus || "—"} kind={statusKind(runStatus)} />
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" display="block">RESULTS</Typography>
              <Typography variant="body2">{results.length} rows · {passN} pass</Typography>
            </Box>
          </Stack>
        </Section>
      )}

      {/* Live results table */}
      <Section title="Test results" subtitle={runId ? `Run ${runId}` : "Start a test to see results"} bodyPad={0} sx={{ mb: 2 }}>
        {results.length === 0 ? (
          <EmptyState message={runId ? "Waiting for results…" : "No active run."} />
        ) : (
          <Table>
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: 64 }}>S.No</TableCell>
                <TableCell>Test name</TableCell>
                <TableCell align="right">Expected</TableCell>
                <TableCell align="right">Measured</TableCell>
                <TableCell>Result</TableCell>
                <TableCell align="right">Cycle time</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {results.map((r, i) => (
                <TableRow key={i}>
                  <TableCell sx={{ fontFamily: MONO_STACK }}>{r.serial_no ?? i + 1}</TableCell>
                  <TableCell>{r.test_name}</TableCell>
                  <TableCell align="right" sx={{ fontFamily: MONO_STACK }}>{String(r.expected ?? "")}</TableCell>
                  <TableCell align="right" sx={{ fontFamily: MONO_STACK }}>{String(r.measured ?? "")}</TableCell>
                  <TableCell>{r.result ? <StatusChip label={r.result} kind={statusKind(r.result)} /> : "—"}</TableCell>
                  <TableCell align="right" sx={{ fontFamily: MONO_STACK }}>{r.cycle_time_ms != null ? `${r.cycle_time_ms} ms` : ""}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>

      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        <Section title="Run history" sx={{ flex: 1 }} bodyPad={0}>
          {runs.length === 0 ? <EmptyState message="No runs yet." /> : (
            <Table>
              <TableHead><TableRow><TableCell>Run</TableCell><TableCell>Recipe</TableCell><TableCell>Status</TableCell></TableRow></TableHead>
              <TableBody>
                {runs.map((r) => {
                  const d = r.data ?? {};
                  const s = d.result || d.status || "?";
                  return (
                    <TableRow key={r.id} hover sx={{ cursor: "pointer" }} onClick={() => openRun(r.id)}>
                      <TableCell sx={{ fontFamily: MONO_STACK }}>{r.id}</TableCell>
                      <TableCell sx={{ fontFamily: MONO_STACK }}>{d.recipe_id || "—"}</TableCell>
                      <TableCell><StatusChip label={s} kind={statusKind(s)} /></TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </Section>

        <Section title="Station events" subtitle="Live feed" sx={{ flex: 1 }}>
          {events.length === 0 ? <EmptyState message="Waiting for events…" /> : (
            <Box sx={{ maxHeight: 320, overflow: "auto" }}>
              <Stack spacing={0.75}>
                {events.map((e, i) => (
                  <Stack key={i} direction="row" spacing={1} alignItems="center" sx={{ py: 0.5, borderBottom: "1px solid", borderColor: "divider" }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontFamily: MONO_STACK, minWidth: 64 }}>{fmtTime(e.ts)}</Typography>
                    <Typography variant="body2" fontWeight={600} sx={{ minWidth: 100 }}>{e.type}</Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ fontFamily: MONO_STACK, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {JSON.stringify(e.payload ?? {})}
                    </Typography>
                  </Stack>
                ))}
              </Stack>
            </Box>
          )}
        </Section>
      </Stack>

      {/* Start dialog */}
      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Start test</DialogTitle>
        <DialogContent>
          <Tabs value={mode} onChange={(_, v) => setMode(v)} sx={{ mb: 2 }}>
            <Tab icon={<QrCodeScanner fontSize="small" />} iconPosition="start" label="Barcode" value="barcode" />
            <Tab label="Select recipe" value="recipe" />
          </Tabs>
          {mode === "barcode" ? (
            <Stack spacing={1.5}>
              <TextField label="Scan / enter barcode" value={barcode} autoFocus
                onChange={(e) => setBarcode(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && barcode) startRun(); }} />
              <Typography variant="caption" color="text.secondary">
                Resolved recipe: <b style={{ fontFamily: MONO_STACK }}>{resolvedPreview || "—"}</b> (first {prefixLen} chars)
              </Typography>
            </Stack>
          ) : (
            <TextField select fullWidth label="Recipe" value={pickRecipe} onChange={(e) => setPickRecipe(e.target.value)}>
              {recipes.length === 0 && <MenuItem value="" disabled>No recipes</MenuItem>}
              {recipes.map((r) => <MenuItem key={r.recipe_id} value={r.recipe_id}>{r.name} ({r.recipe_id})</MenuItem>)}
            </TextField>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="contained" startIcon={<PlayArrow />}
            disabled={mode === "barcode" ? !barcode : !pickRecipe} onClick={startRun}>
            Start
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
