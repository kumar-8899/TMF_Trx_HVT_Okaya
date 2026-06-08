import {
  Alert, Box, Button, Chip, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow,
  TextField, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useStream } from "../hooks/useStream";

interface EventEnvelope {
  type: string;
  ts: number;
  payload?: Record<string, unknown>;
}

export function Runs() {
  const { can } = useAuth();
  const [recipeId, setRecipeId] = useState("");
  const [version, setVersion] = useState("");
  const [runs, setRuns] = useState<any[]>([]);
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [error, setError] = useState<string | null>(null);

  const { last } = useStream<EventEnvelope>("/ws/station");

  const refresh = () => api.get("/runs").then(setRuns).catch((e) => setError(e.message));
  useEffect(() => { refresh(); }, []);
  useEffect(() => {
    if (last) {
      setEvents((prev) => [last, ...prev].slice(0, 50));
      if (String(last.type).startsWith("run-")) refresh();
    }
  }, [last]);

  const start = async () => {
    setError(null);
    try {
      const body: Record<string, unknown> = { recipe_id: recipeId };
      if (version) body.version = Number(version);
      await api.post("/runs/start", body);
    } catch (e: any) { setError(e.message); }
  };
  const abort = async () => {
    setError(null);
    try { await api.post("/runs/abort", {}); } catch (e: any) { setError(e.message); }
  };

  return (
    <Stack spacing={2}>
      <Typography variant="h5">Runs</Typography>

      {can("TEST.RUN") && (
        <Paper sx={{ p: 2 }}>
          <Stack direction="row" spacing={1} alignItems="center">
            <TextField size="small" label="recipe_id" value={recipeId} onChange={(e) => setRecipeId(e.target.value)} />
            <TextField size="small" label="version" value={version} onChange={(e) => setVersion(e.target.value)} sx={{ width: 100 }} />
            <Button variant="contained" onClick={start} disabled={!recipeId}>Start run</Button>
            <Button variant="outlined" color="error" onClick={abort}>Abort</Button>
          </Stack>
        </Paper>
      )}
      {error && <Alert severity="error">{error}</Alert>}

      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        <Paper sx={{ p: 2, flex: 1 }}>
          <Typography variant="h6">Run records</Typography>
          <Table size="small">
            <TableHead><TableRow><TableCell>Run</TableCell><TableCell>Status</TableCell></TableRow></TableHead>
            <TableBody>
              {runs.map((r) => (
                <TableRow key={r.id}>
                  <TableCell>{r.id}</TableCell>
                  <TableCell><Chip size="small" label={r.data?.status ?? "?"}
                    color={r.data?.status === "finished" ? "success" : "default"} /></TableCell>
                </TableRow>
              ))}
              {runs.length === 0 && <TableRow><TableCell colSpan={2}>No runs.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </Paper>

        <Paper sx={{ p: 2, flex: 1 }}>
          <Typography variant="h6">Station events (live)</Typography>
          <Box sx={{ maxHeight: 300, overflow: "auto", fontFamily: "monospace", fontSize: 12 }}>
            {events.map((e, i) => (
              <div key={i}>{e.type} — {JSON.stringify(e.payload ?? {})}</div>
            ))}
            {events.length === 0 && <Typography variant="body2">Waiting for events…</Typography>}
          </Box>
        </Paper>
      </Stack>
    </Stack>
  );
}
