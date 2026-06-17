import { PlayArrow, Stop } from "@mui/icons-material";
import {
  Alert, Box, Button, Divider, Grid, Stack, TextField, Typography,
} from "@mui/material";
import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageHeader, Section, StatusChip } from "../components/ui";
import { Sparkline } from "../components/Sparkline";
import { useStream } from "../hooks/useStream";
import { MONO_STACK } from "../theme/theme";

interface Frame {
  t: number;
  seq: number;
  values: Record<string, number>;
}

const HISTORY = 60; // frames kept per channel for the sparkline

function ChannelTile({ name, value, history }: { name: string; value: number; history: number[] }) {
  return (
    <Grid item xs={6} sm={4} md={3}>
      <Box sx={{ p: 1.5, border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
        <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: "0.05em" }}>
          {name}
        </Typography>
        <Typography sx={{ fontFamily: MONO_STACK, fontSize: 22, fontWeight: 600, lineHeight: 1.2 }}>
          {Number.isFinite(value) ? value.toFixed(3) : "—"}
        </Typography>
        <Sparkline data={history} width={140} height={28} />
      </Box>
    </Grid>
  );
}

function SignalCard({ signal }: { signal: "ai" | "di" }) {
  const { can } = useAuth();
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // How many channels to acquire (ai0..ai{n-1}) and the sample rate (Hz). Both
  // are sent to LabVIEW in the start command: daq.{signal}.stream.start
  // { rate?, channels? } (LABVIEW_BRIDGE.md §5.1). Blank = let LabVIEW decide.
  const [channels, setChannels] = useState("1");
  const [rate, setRate] = useState("");
  const { last, status } = useStream<Frame>(running ? `/instruments/daq/${signal}/stream/ws` : null);

  // Per-channel ring buffer for sparklines.
  const histRef = useRef<Record<string, number[]>>({});
  const [, force] = useState(0);
  useEffect(() => {
    if (!last?.values) return;
    for (const [k, v] of Object.entries(last.values)) {
      const arr = histRef.current[k] ?? [];
      arr.push(Number(v));
      if (arr.length > HISTORY) arr.shift();
      histRef.current[k] = arr;
    }
    force((n) => n + 1);
  }, [last?.seq]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = async (action: "start" | "stop") => {
    setError(null);
    try {
      const args: Record<string, number> = {};
      if (action === "start") {
        const n = parseInt(channels, 10);
        const r = parseFloat(rate);
        if (Number.isFinite(n) && n > 0) args.channels = n;
        if (Number.isFinite(r) && r > 0) args.rate = r;
      }
      await api.post(`/instruments/daq/${signal}/stream/${action}`, args);
      setRunning(action === "start");
      if (action === "stop") histRef.current = {};
    } catch (e: any) {
      setError(e.message);
    }
  };

  const statusLabel = running ? (status === "open" ? "streaming" : status) : "stopped";
  const values = last?.values ?? {};

  return (
    <Section
      title={`${signal.toUpperCase()} stream`}
      subtitle={signal === "ai" ? "Analog input" : "Digital input"}
      actions={<StatusChip label={statusLabel} kind={running && status === "open" ? "running" : "idle"} />}
      sx={{ flex: 1, minWidth: 320 }}
    >
      {can("TEST.RUN") && (
        <Stack direction="row" spacing={1} sx={{ mb: 1.5 }} alignItems="center" flexWrap="wrap" useFlexGap>
          <TextField type="number" label="channels" value={channels} disabled={running} sx={{ width: 110 }}
            inputProps={{ min: 1, "aria-label": `${signal}-channels` }}
            onChange={(e) => setChannels(e.target.value)} />
          <TextField type="number" label="rate (Hz)" value={rate} disabled={running} sx={{ width: 110 }}
            inputProps={{ min: 0, "aria-label": `${signal}-rate` }}
            onChange={(e) => setRate(e.target.value)} />
          <Button variant="contained" startIcon={<PlayArrow />} disabled={running} onClick={() => toggle("start")}>
            Start
          </Button>
          <Button variant="outlined" color="inherit" startIcon={<Stop />} disabled={!running} onClick={() => toggle("stop")}>
            Stop
          </Button>
        </Stack>
      )}
      {error && <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert>}

      {Object.keys(values).length === 0 ? (
        <EmptyState message={running ? "Waiting for frames…" : "Stream stopped. Press Start to acquire."} />
      ) : (
        <Grid container spacing={1.5}>
          {Object.entries(values).map(([k, v]) => (
            <ChannelTile key={k} name={k} value={Number(v)} history={histRef.current[k] ?? []} />
          ))}
        </Grid>
      )}
      {last && (
        <>
          <Divider sx={{ my: 1.5 }} />
          <Typography variant="caption" color="text.secondary" sx={{ fontFamily: MONO_STACK }}>
            seq {last.seq} · t {last.t}
          </Typography>
        </>
      )}
    </Section>
  );
}

function Variables() {
  const { can } = useAuth();
  const [name, setName] = useState("vbus_main");
  const [value, setValue] = useState<string>("");
  const [result, setResult] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  const read = async () => {
    setError(null);
    try { setResult(JSON.stringify(await api.get(`/variables/${name}/value`))); }
    catch (e: any) { setError(e.message); }
  };
  const write = async (v: number) => {
    setError(null);
    try {
      await api.put(`/variables/${name}/value`, { value: v });
      setResult(`wrote ${v} → ${name}`);
    } catch (e: any) { setError(e.message); }
  };

  return (
    <Section title="Variables" subtitle="Read retained values · write setpoints and digital outputs">
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <TextField label="variable" value={name} onChange={(e) => setName(e.target.value)} sx={{ width: 200 }} />
        <Button variant="outlined" onClick={read}>Read</Button>
        {can("TEST.RUN") && (
          <>
            <Divider orientation="vertical" flexItem />
            <TextField label="value" value={value} onChange={(e) => setValue(e.target.value)} sx={{ width: 120 }} />
            <Button variant="contained" disabled={value === ""} onClick={() => write(Number(value))}>Write</Button>
            <Typography variant="caption" color="text.secondary">DO:</Typography>
            <Button size="small" variant="outlined" color="inherit" onClick={() => write(0)}>Set 0</Button>
            <Button size="small" variant="outlined" color="inherit" onClick={() => write(1)}>Set 1</Button>
          </>
        )}
      </Stack>
      {error && <Alert severity="error" sx={{ mt: 1.5 }}>{error}</Alert>}
      {result && (
        <Typography variant="body2" sx={{ mt: 1.5, fontFamily: MONO_STACK }}>{result}</Typography>
      )}
    </Section>
  );
}

export function Daq() {
  return (
    <Box>
      <PageHeader title="DAQ" subtitle="LabVIEW-backed instruments — streams and station variables" />
      <Stack spacing={2}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
          <SignalCard signal="ai" />
          <SignalCard signal="di" />
        </Stack>
        <Variables />
      </Stack>
    </Box>
  );
}
