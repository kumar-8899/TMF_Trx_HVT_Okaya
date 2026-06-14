import {
  Alert, Box, Button, Chip, Paper, Stack, TextField, Typography,
} from "@mui/material";
import { useState } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useStream } from "../hooks/useStream";

interface Frame {
  t: number;
  seq: number;
  values: Record<string, number>;
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
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <Paper sx={{ p: 2, flex: 1 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="h6">{signal.toUpperCase()} stream</Typography>
        <Chip size="small" label={running ? status : "stopped"}
          color={status === "open" ? "success" : "default"} />
      </Stack>
      {can("TEST.RUN") && (
        <Stack direction="row" spacing={1} sx={{ my: 1 }} alignItems="center">
          <TextField size="small" type="number" label="channels" value={channels}
            disabled={running} sx={{ width: 100 }}
            inputProps={{ min: 1, "aria-label": `${signal}-channels` }}
            onChange={(e) => setChannels(e.target.value)} />
          <TextField size="small" type="number" label="rate (Hz)" value={rate}
            disabled={running} sx={{ width: 100 }}
            inputProps={{ min: 0, "aria-label": `${signal}-rate` }}
            onChange={(e) => setRate(e.target.value)} />
          <Button size="small" variant="contained" disabled={running} onClick={() => toggle("start")}>Start</Button>
          <Button size="small" variant="outlined" disabled={!running} onClick={() => toggle("stop")}>Stop</Button>
        </Stack>
      )}
      {error && <Alert severity="error">{error}</Alert>}
      <Box component="pre" sx={{ fontSize: 12, minHeight: 60 }}>
        {last ? JSON.stringify(last.values, null, 2) : "—"}
      </Box>
      {last && <Typography variant="caption">seq {last.seq}</Typography>}
    </Paper>
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
  const write = async () => {
    setError(null);
    try {
      await api.put(`/variables/${name}/value`, { value: Number(value) });
      setResult(`wrote ${value}`);
    } catch (e: any) { setError(e.message); }
  };

  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="h6">Variables</Typography>
      <Stack direction="row" spacing={1} sx={{ my: 1 }} alignItems="center">
        <TextField size="small" label="variable" value={name} onChange={(e) => setName(e.target.value)} />
        <Button size="small" onClick={read}>Read</Button>
        {can("TEST.RUN") && <>
          <TextField size="small" label="value" value={value} onChange={(e) => setValue(e.target.value)} />
          <Button size="small" onClick={write}>Write</Button>
        </>}
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
      {result && <Typography variant="body2">{result}</Typography>}
    </Paper>
  );
}

export function Daq() {
  return (
    <Stack spacing={2}>
      <Typography variant="h5">DAQ</Typography>
      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        <SignalCard signal="ai" />
        <SignalCard signal="di" />
      </Stack>
      <Variables />
    </Stack>
  );
}
