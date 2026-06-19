import { PlayArrow, QrCodeScanner, Stop } from "@mui/icons-material";
import {
  Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack,
  Tab, Tabs, TextField, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { PageHeader, Section } from "../components/ui";
import { LiveVariablesPanel, type LiveVariable } from "../components/testing/LiveVariablesPanel";
import { MessageLine } from "../components/testing/MessageLine";
import { ResultsTable, type ResultRow } from "../components/testing/ResultsTable";
import { TodayStrip } from "../components/testing/TodayStrip";
import { VerdictBanner } from "../components/testing/VerdictBanner";
import { useStream } from "../hooks/useStream";
import { useValues } from "../hooks/useValues";
import { MONO_STACK } from "../theme/theme";

interface EventEnvelope { type: string; ts: number; payload?: Record<string, any> }
interface Profile {
  acquisition: { default_mode: string; barcode: { length: number } };
  live_variables: LiveVariable[];
  ui: { verdict_banner: boolean; message_line: boolean; today_strip: boolean };
}

const FINAL = new Set(["PASS", "FAIL", "ABORTED"]);

export function Runs() {
  const { can } = useAuth();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  // active / selected run
  const [runId, setRunId] = useState<string | null>(null);
  const [serial, setSerial] = useState("");
  const [model, setModel] = useState("");
  const [runStatus, setRunStatus] = useState("");
  const [results, setResults] = useState<ResultRow[]>([]);
  const [message, setMessage] = useState("");
  const [errLine, setErrLine] = useState("");

  // start dialog
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"barcode" | "recipe">("barcode");
  const [barcode, setBarcode] = useState("");
  const [pickRecipe, setPickRecipe] = useState("");
  const [recipes, setRecipes] = useState<{ recipe_id: string; name: string }[]>([]);

  const { last } = useStream<EventEnvelope>("/ws/station");
  const values = useValues("/instruments/values/ws");

  const refresh = () => api.get("/runs").then(setRuns).catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
    api.get("/runs/config").then((p) => { setProfile(p); setMode(p.acquisition?.default_mode === "recipe" ? "recipe" : "barcode"); }).catch(() => {});
    api.get("/recipes").then(setRecipes).catch(() => {});
  }, []);

  useEffect(() => {
    if (!last) return;
    const t = String(last.type);
    const body = last.payload ?? {};
    if (t.startsWith("run-")) refresh();
    // message/status line from any event
    if (body.message) setMessage(String(body.message));
    else if (t) setMessage(t.replace(/-/g, " "));
    if (/fail|error|safety|abort/i.test(t) || body.level === "error") setErrLine(String(body.reason || body.error || body.message || t));
    if (t === "run-started") setErrLine("");
    if (runId && body.run_id === runId) {
      if (t === "test-result") setResults((prev) => [...prev, body as ResultRow]);
      else if (t === "run-finished") { setRunStatus(body.result || "finished"); reopenForNext(); }
      else if (t === "run-aborted") { setRunStatus("ABORTED"); reopenForNext(); }
    }
  }, [last]); // eslint-disable-line react-hooks/exhaustive-deps

  const running = runStatus === "running";
  const prefixLen = profile?.acquisition?.barcode?.length ?? 3;
  const resolvedPreview = barcode.trim().slice(0, prefixLen);

  // After a run ends, auto-prompt for the next unit (operator presses Start once).
  const reopenForNext = () => {
    setMode(profile?.acquisition?.default_mode === "recipe" ? "recipe" : "barcode");
    setBarcode(""); setPickRecipe(""); setOpen(true);
  };

  const startRun = async () => {
    setError(null);
    try {
      const reqBody = mode === "barcode" ? { barcode } : { recipe_id: pickRecipe };
      const res = await api.post("/runs/start", reqBody);
      setRunId(res.run_id); setModel(res.model || res.recipe_id || ""); setSerial(res.serial_no || "");
      setRunStatus("running"); setResults([]); setErrLine(""); setMessage("Run started");
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
      setRunId(id); setModel(d.model || d.recipe_id || ""); setSerial(d.serial_no || "");
      setResults(d.results || []); setRunStatus(d.result || d.status || "");
    } catch (e: any) { setError(e.message); }
  };

  const ui = profile?.ui ?? { verdict_banner: true, message_line: true, today_strip: true };
  const finalVerdict = FINAL.has(String(runStatus).toUpperCase()) ? runStatus : undefined;

  return (
    <Box>
      <PageHeader
        title="Test Bench"
        subtitle="Operator testing window"
        actions={can("TEST.RUN") && (
          <>
            <Button variant="contained" startIcon={<PlayArrow />} disabled={running} onClick={() => setOpen(true)}>Start test</Button>
            <Button variant="outlined" color="error" startIcon={<Stop />} disabled={!running} onClick={abort}>Abort</Button>
          </>
        )}
      />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Stack spacing={2}>
        {/* identity + status banner */}
        <Section>
          <Stack direction="row" spacing={4} alignItems="center" flexWrap="wrap" useFlexGap>
            <Field label="Serial No" value={serial || "—"} />
            <Field label="Model" value={model || "—"} />
            <Field label="Run" value={runId || "—"} />
            <Field label="Status" value={(runStatus || "idle").toString()} />
            <Field label="Results" value={`${results.length}`} />
          </Stack>
        </Section>

        {ui.verdict_banner && <VerdictBanner result={finalVerdict} />}
        {ui.message_line && <MessageLine message={message} error={errLine || undefined} />}

        <Stack direction={{ xs: "column", lg: "row" }} spacing={2} alignItems="stretch">
          <Box sx={{ flex: 2, minWidth: 0 }}>
            <ResultsTable rows={results} subtitle={runId ? `Run ${runId}` : "Start a test to see results"} />
          </Box>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <LiveVariablesPanel variables={profile?.live_variables ?? []} values={values} />
          </Box>
        </Stack>

        {ui.today_strip && <TodayStrip runs={runs} onSelect={openRun} />}
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
                Model / recipe: <b style={{ fontFamily: MONO_STACK }}>{resolvedPreview || "—"}</b> · Serial: <b style={{ fontFamily: MONO_STACK }}>{barcode || "—"}</b>
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
            disabled={mode === "barcode" ? !barcode : !pickRecipe} onClick={startRun}>Start</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: "0.06em", display: "block" }}>{label}</Typography>
      <Typography sx={{ fontFamily: MONO_STACK, fontWeight: 600 }}>{value}</Typography>
    </Box>
  );
}
