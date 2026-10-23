import { Delete, Done, RestartAlt } from "@mui/icons-material";
import {
  Alert, Box, Button, Chip, IconButton, MenuItem, Stack, Table, TableBody, TableCell,
  TableHead, TableRow, TextField, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client";
import { MONO_STACK } from "../../theme/theme";
import { StationPicker } from "../StationPicker";
import { Section } from "../ui";

/** Maintenance → Calibration (docs/contracts/CALIBRATION.md). Analog input: read the raw value,
 * type what the reference meter shows. Analog output: command a raw value, type what the meter
 * measures. Two or more points → least-squares gain/offset (fitted by the backend, so the UI and
 * the controller can never disagree) → saved as an OVERLAY on the shipped map and hot-reloaded —
 * no relaunch. Gated MAINTENANCE.CALIBRATE; driving an output also needs maintenance mode. */

interface CalSignal {
  name: string; units?: string | null; readable: boolean; writable: boolean;
  factory: { gain: number; offset: number };
  calibration: { gain: number; offset: number; n?: number; max_error?: number; updated_ts?: number; by?: string } | null;
}
interface Point { raw: number; reference: number }
interface Fit { gain: number; offset: number; n: number; max_error: number }

const num = (v: string) => (v.trim() === "" || Number.isNaN(Number(v)) ? null : Number(v));
const fmt = (n: number) => Number(n.toPrecision(6)).toString();

export function CalibrationPanel({ maintenanceOn }: { maintenanceOn: boolean }) {
  const [station, setStation] = useState<string | null>(null);
  const [signals, setSignals] = useState<CalSignal[]>([]);
  const [sel, setSel] = useState("");
  const [mode, setMode] = useState<"input" | "output">("input");
  const [points, setPoints] = useState<Point[]>([]);
  const [raw, setRaw] = useState<number | null>(null);        // captured / commanded raw
  const [driveRaw, setDriveRaw] = useState("");
  const [ref, setRef] = useState("");
  const [fit, setFit] = useState<Fit | null>(null);
  const [fitError, setFitError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ severity: "success" | "warning"; text: string } | null>(null);

  const qs = station ? `?station=${encodeURIComponent(station)}` : "";
  const body = (extra: object = {}) => ({ station: station ?? undefined, ...extra });
  const signal = signals.find((s) => s.name === sel) ?? null;

  const load = useCallback(() => {
    api.get(`/calibration/signals${qs}`)
      .then((r: CalSignal[]) => { setSignals(r); setError(null); })
      .catch((e: any) => setError(e.message));
  }, [qs]);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    setPoints([]); setRaw(null); setRef(""); setDriveRaw(""); setNotice(null);
    if (signal) setMode(signal.readable ? "input" : "output");
  }, [sel, station]);                                          // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {                                             // live fit preview from the backend
    if (points.length < 2) { setFit(null); setFitError(null); return; }
    api.post("/calibration/fit", { points })
      .then((f: Fit) => { setFit(f); setFitError(null); })
      .catch((e: any) => { setFit(null); setFitError(e.message); });
  }, [points]);

  const guard = async (fn: () => Promise<void>) => {
    setError(null);
    try { await fn(); } catch (e: any) { setError(e.message); }
  };

  const capture = () => guard(async () => {
    const r = await api.post(`/calibration/${sel}/raw`, body());
    setRaw(r.raw);
  });
  const drive = () => guard(async () => {
    const v = num(driveRaw);
    if (v === null) throw new Error("enter the raw value to command");
    await api.post(`/calibration/${sel}/drive`, body({ raw: v }));
    setRaw(v);
  });
  const addPoint = () => {
    const r = num(ref);
    if (raw === null || r === null) return;
    setPoints((p) => [...p, { raw, reference: r }]);
    setRaw(null); setRef(""); setDriveRaw("");
  };
  const apply = () => guard(async () => {
    const r = await api.post(`/calibration/${sel}/apply`, body({ points }));
    setNotice(r.controller === "pending"
      ? { severity: "warning", text: `Saved. ${r.detail ?? "The controller will pick it up on its next start."}` }
      : { severity: "success", text: `Calibration applied (gain ${fmt(r.gain)}, offset ${fmt(r.offset)}) — live now, no restart.` });
    setPoints([]); load();
  });
  const reset = () => guard(async () => {
    if (!window.confirm(`Reset ${sel} to its factory scale?`)) return;
    const r = await api.del(`/calibration/${sel}${qs}`);
    setNotice(r.controller === "pending"
      ? { severity: "warning", text: `Reset saved. ${r.detail ?? ""}` }
      : { severity: "success", text: "Reset to factory scale." });
    setPoints([]); load();
  });

  const needsMaint = mode === "output" && !maintenanceOn;

  return (
    <Section title="Calibration" subtitle="analog input & output · overlay on the shipped variable map · no restart">
      <Stack spacing={2}>
        {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
        {notice && <Alert severity={notice.severity} onClose={() => setNotice(null)}>{notice.text}</Alert>}
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <StationPicker value={station} onChange={setStation} />
          <TextField select size="small" label="signal" value={sel} onChange={(e) => setSel(e.target.value)}
            sx={{ minWidth: 220 }} inputProps={{ "aria-label": "calibration signal" }}>
            {signals.map((s) => (
              <MenuItem key={s.name} value={s.name}>
                {s.name}{s.units ? ` (${s.units})` : ""}{s.calibration ? " ✓" : ""}
              </MenuItem>
            ))}
          </TextField>
          {signal && signal.readable && signal.writable && (
            <ToggleButtonGroup size="small" exclusive value={mode} onChange={(_, v) => v && setMode(v)}>
              <ToggleButton value="input">Input (read)</ToggleButton>
              <ToggleButton value="output">Output (drive)</ToggleButton>
            </ToggleButtonGroup>
          )}
        </Stack>
        {!signals.length && !error && (
          <Typography variant="body2" color="text.secondary">No calibratable signals on this station.</Typography>
        )}

        {signal && (
          <>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip size="small" label={`factory: gain ${fmt(signal.factory.gain)}, offset ${fmt(signal.factory.offset)}`} />
              {signal.calibration
                ? <Chip size="small" color="success"
                    label={`calibrated: gain ${fmt(signal.calibration.gain)}, offset ${fmt(signal.calibration.offset)}`
                      + (signal.calibration.by ? ` · ${signal.calibration.by}` : "")} />
                : <Chip size="small" variant="outlined" label="not calibrated" />}
            </Stack>

            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              {mode === "input"
                ? <Button variant="outlined" onClick={capture}>Capture raw reading</Button>
                : <>
                    <TextField size="small" label="raw to command" value={driveRaw} sx={{ width: 150 }}
                      onChange={(e) => setDriveRaw(e.target.value)} disabled={!maintenanceOn} />
                    <Button variant="outlined" onClick={drive} disabled={!maintenanceOn || num(driveRaw) === null}>
                      Drive output
                    </Button>
                  </>}
              <Typography variant="body2" sx={{ fontFamily: MONO_STACK, minWidth: 130 }}>
                {raw === null ? "raw: —" : `raw: ${fmt(raw)}`}
              </Typography>
              <TextField size="small" label={`reference meter${signal.units ? ` (${signal.units})` : ""}`}
                value={ref} onChange={(e) => setRef(e.target.value)} sx={{ width: 190 }} disabled={raw === null} />
              <Button variant="contained" onClick={addPoint} disabled={raw === null || num(ref) === null}>
                Add point
              </Button>
            </Stack>
            {needsMaint && <Alert severity="info" sx={{ py: 0 }}>Enter maintenance mode to drive an output.</Alert>}

            {points.length > 0 && (
              <Table size="small">
                <TableHead><TableRow><TableCell>#</TableCell><TableCell>raw</TableCell>
                  <TableCell>reference</TableCell><TableCell /></TableRow></TableHead>
                <TableBody>
                  {points.map((p, i) => (
                    <TableRow key={i}>
                      <TableCell>{i + 1}</TableCell>
                      <TableCell sx={{ fontFamily: MONO_STACK }}>{fmt(p.raw)}</TableCell>
                      <TableCell sx={{ fontFamily: MONO_STACK }}>{fmt(p.reference)}</TableCell>
                      <TableCell align="right">
                        <IconButton size="small" aria-label={`remove point ${i + 1}`}
                          onClick={() => setPoints((ps) => ps.filter((_, j) => j !== i))}><Delete fontSize="small" /></IconButton>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}

            <Box>
              {fit && (
                <Typography variant="body2" sx={{ fontFamily: MONO_STACK }} data-testid="cal-fit">
                  fit: gain {fmt(fit.gain)} · offset {fmt(fit.offset)} · max error {fmt(fit.max_error)}
                  {signal.units ? ` ${signal.units}` : ""} · {fit.n} points
                </Typography>
              )}
              {fitError && points.length >= 2 && <Alert severity="warning" sx={{ py: 0 }}>{fitError}</Alert>}
              {points.length === 1 && <Typography variant="caption" color="text.secondary">Add at least one more point at a different value.</Typography>}
            </Box>

            <Stack direction="row" spacing={1}>
              <Button variant="contained" color="success" startIcon={<Done />} onClick={apply} disabled={!fit}>
                Apply calibration
              </Button>
              <Button variant="outlined" color="warning" startIcon={<RestartAlt />} onClick={reset}
                disabled={!signal.calibration}>Reset to factory</Button>
            </Stack>
          </>
        )}
      </Stack>
    </Section>
  );
}
