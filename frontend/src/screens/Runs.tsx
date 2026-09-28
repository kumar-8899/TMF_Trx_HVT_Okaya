import { PlayArrow, Stop } from "@mui/icons-material";
import {
  Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack,
  TextField, Typography,
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
import { StationPicker } from "../components/StationPicker";
import { useRunActivity } from "../components/RunActivity";
import { useStream } from "../hooks/useStream";
import { useValues } from "../hooks/useValues";
import { MONO_STACK } from "../theme/theme";

interface EventEnvelope { type: string; ts: number; payload?: Record<string, any> }
interface Profile {
  live_variables: LiveVariable[];
  ui: { verdict_banner: boolean; message_line: boolean; today_strip: boolean };
}
interface BarcodePart { name: string; start: number; length: number }
interface BarcodeConfig {
  enabled: boolean; length: number; parts: BarcodePart[]; recipe_part: string | null;
  submit_on_enter?: boolean;
}
const NO_BARCODE: BarcodeConfig = { enabled: false, length: 0, parts: [], recipe_part: null };

const FINAL = new Set(["PASS", "FAIL", "ABORTED"]);

export function Runs() {
  const { can, principal } = useAuth();
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
  const [barcodeCfg, setBarcodeCfg] = useState<BarcodeConfig>(NO_BARCODE);
  const [barcode, setBarcode] = useState("");
  const [pickRecipe, setPickRecipe] = useState("");
  const [recipes, setRecipes] = useState<{ recipe_id: string; name: string }[]>([]);

  const [station, setStation] = useState<string | null>(null);   // multi-socket: which DUT position
  const values = useValues("/instruments/values/ws");

  const refresh = () => api.get("/runs").then(setRuns).catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
    api.get("/runs/config").then(setProfile).catch(() => {});
    api.get("/config/barcode").then(setBarcodeCfg).catch(() => {});
    api.get("/recipes").then(setRecipes).catch(() => {});
  }, []);

  // current shift (refresh each minute so it flips at a shift boundary)
  const [shift, setShift] = useState<any | null>(null);
  useEffect(() => {
    const load = () => api.get("/config/shift/current").then(setShift).catch(() => {});
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);

  const running = runStatus === "running";
  const recipeSlicePart = barcodeCfg.parts.find((p) => p.name === barcodeCfg.recipe_part);
  const resolvedPreview = recipeSlicePart
    ? barcode.trim().slice(recipeSlicePart.start, recipeSlicePart.start + recipeSlicePart.length)
    : "";

  // #6.5 lock the shell to this screen while a run runs (only Abort reachable).
  const { setActive } = useRunActivity();
  useEffect(() => { setActive(running); return () => setActive(false); }, [running]); // eslint-disable-line react-hooks/exhaustive-deps

  // After a run ends, auto-prompt for the next unit (operator presses Start once).
  const reopenForNext = () => { setBarcode(""); setPickRecipe(""); setOpen(true); };

  // Every station event, without loss (onMessage fires per frame — see useStream). A run
  // bursts its test-results, so accumulating from `last` would drop most of them.
  useStream<EventEnvelope>(`/ws/station${station ? `?station=${encodeURIComponent(station)}` : ""}`, {
    onMessage: (ev) => {
      const t = String(ev.type);
      const body = ev.payload ?? {};
      if (t.startsWith("run-")) refresh();
      if (body.message) setMessage(String(body.message));
      else if (t) setMessage(t.replace(/-/g, " "));
      if (/fail|error|safety|abort/i.test(t) || body.level === "error") setErrLine(String(body.reason || body.error || body.message || t));
      if (t === "run-started") setErrLine("");
      if (runId && body.run_id === runId) {
        if (t === "test-result") setResults((prev) => [...prev, body as ResultRow]);
        else if (t === "run-finished") { setRunStatus(body.result || "finished"); reconcile(runId); reopenForNext(); }
        else if (t === "run-aborted") { setRunStatus("ABORTED"); reconcile(runId); reopenForNext(); }
      }
    },
  });

  // On terminal, sync to the persisted record — authoritative + complete. The backend writes
  // results asynchronously (broadcast happens before persistence), so the tail may not be
  // written the instant run-finished arrives on the WS. Poll until the RECORD's status is
  // terminal: run-finished persists status="finished" under the same per-run lock, AFTER every
  // test-result (asyncio.Lock is FIFO), so status=finished ⇒ all results are present.
  const reconcile = (id: string) => {
    let tries = 0;
    const tick = async () => {
      tries += 1;
      try {
        const d = (await api.get(`/runs/${id}`))?.data;
        if (Array.isArray(d?.results)) setResults(d.results as ResultRow[]);
        if (d?.status === "finished" || d?.status === "aborted") return;   // results complete
      } catch { /* transient */ }
      if (tries < 25) setTimeout(tick, 300);   // ~7.5s ceiling
    };
    tick();
  };

  const startRun = async () => {
    setError(null);
    try {
      const reqBody: any = barcodeCfg.enabled ? { barcode } : { recipe_id: pickRecipe };
      if (station) reqBody.station = station;
      const res = await api.post("/runs/start", reqBody);
      setRunId(res.run_id); setModel(res.model || res.recipe_id || ""); setSerial(res.serial_no || "");
      setRunStatus("running"); setResults([]); setErrLine(""); setMessage("Run started");
      setOpen(false); setBarcode(""); setPickRecipe("");
      refresh();
    } catch (e: any) { setError(e.message); }
  };
  const abort = async () => {
    setError(null);
    try { await api.post("/runs/abort", station ? { station } : {}); } catch (e: any) { setError(e.message); }
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
            <StationPicker value={station} onChange={setStation} />
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
            <Field label="Inspector" value={principal?.username || "—"} />
            <Field label="Status" value={(runStatus || "idle").toString()} />
            <Field label="Results" value={`${results.length}`} />
            {shift?.enabled && <Field label="Shift" value={shift.shift_label || "—"} />}
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
          {barcodeCfg.enabled ? (
            <Stack spacing={1.5} sx={{ mt: 1 }}>
              <TextField label="Serial number" value={barcode} autoFocus
                onChange={(e) => setBarcode(e.target.value)}
                onKeyDown={(e) => {
                  // A real barcode scanner appends Enter to every scan (keyboard-emulation
                  // mode, on by default on virtually every scanner) — so unless a fork has
                  // explicitly opted into scan-to-submit, Enter must only populate the
                  // field, never start the run itself. The operator reviews the resolved
                  // recipe preview and clicks Start explicitly (framework-fix-prompt-2.md
                  // Issue 1).
                  if (e.key === "Enter" && barcode && barcodeCfg.submit_on_enter) startRun();
                }} />
              <Typography variant="caption" color="text.secondary">
                Recipe: <b style={{ fontFamily: MONO_STACK }}>{resolvedPreview || "—"}</b>
              </Typography>
            </Stack>
          ) : (
            <TextField select fullWidth sx={{ mt: 1 }} label="Recipe" value={pickRecipe} onChange={(e) => setPickRecipe(e.target.value)}>
              {recipes.length === 0 && <MenuItem value="" disabled>No recipes</MenuItem>}
              {recipes.map((r) => <MenuItem key={r.recipe_id} value={r.recipe_id}>{r.name} ({r.recipe_id})</MenuItem>)}
            </TextField>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="contained" startIcon={<PlayArrow />}
            disabled={barcodeCfg.enabled ? !barcode : !pickRecipe} onClick={startRun}>Start</Button>
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
