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
  const { last, status } = useStream<Frame>(running ? `/instruments/daq/${signal}/stream/ws` : null);

  const toggle = async (action: "start" | "stop") => {
    setError(null);
    try {
      await api.post(`/instruments/daq/${signal}/stream/${action}`, {});
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
        <Stack direction="row" spacing={1} sx={{ my: 1 }}>
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
