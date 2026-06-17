import { PlayArrow, Stop } from "@mui/icons-material";
import {
  Alert, Box, Button, Stack, Table, TableBody, TableCell, TableHead, TableRow,
  TextField, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageHeader, Section, StatusChip, StatusDot, statusKind } from "../components/ui";
import { useStream } from "../hooks/useStream";
import { MONO_STACK } from "../theme/theme";

interface EventEnvelope {
  type: string;
  ts: number;
  payload?: Record<string, unknown>;
}

function eventKind(type: string) {
  if (/fail|abort|safety|error/i.test(type)) return "fail" as const;
  if (/finish|pass|done|complete/i.test(type)) return "pass" as const;
  if (/start|run-/i.test(type)) return "running" as const;
  return "info" as const;
}

function fmtTime(ts: number) {
  if (!ts) return "";
  const d = new Date(ts * (ts > 1e12 ? 1 : 1000));
  return d.toLocaleTimeString();
}

export function Runs() {
  const { can } = useAuth();
  const [recipeId, setRecipeId] = useState("");
  const [version, setVersion] = useState("");
  const [runs, setRuns] = useState<any[]>([]);
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [error, setError] = useState<string | null>(null);

  const { last, status } = useStream<EventEnvelope>("/ws/station");

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
    <Box>
      <PageHeader
        title="Runs"
        subtitle="Start and monitor test executions on the station"
        actions={
          <Stack direction="row" spacing={0.75} alignItems="center">
            <StatusDot kind={status === "open" ? "pass" : "idle"} />
            <Typography variant="caption" color="text.secondary">
              {status === "open" ? "event feed live" : "feed offline"}
            </Typography>
          </Stack>
        }
      />

      {can("TEST.RUN") && (
        <Section sx={{ mb: 2 }}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <TextField label="recipe_id" value={recipeId} onChange={(e) => setRecipeId(e.target.value)} sx={{ width: 200 }} />
            <TextField label="version" value={version} onChange={(e) => setVersion(e.target.value)} sx={{ width: 100 }} />
            <Button variant="contained" startIcon={<PlayArrow />} onClick={start} disabled={!recipeId}>Start run</Button>
            <Button variant="outlined" color="error" startIcon={<Stop />} onClick={abort}>Abort</Button>
          </Stack>
        </Section>
      )}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        <Section title="Run records" sx={{ flex: 1 }}>
          {runs.length === 0 ? (
            <EmptyState message="No runs yet." />
          ) : (
            <Table>
              <TableHead><TableRow><TableCell>Run</TableCell><TableCell>Status</TableCell></TableRow></TableHead>
              <TableBody>
                {runs.map((r) => {
                  const s = r.data?.status ?? "?";
                  return (
                    <TableRow key={r.id}>
                      <TableCell sx={{ fontFamily: MONO_STACK }}>{r.id}</TableCell>
                      <TableCell><StatusChip label={s} kind={statusKind(s)} /></TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </Section>

        <Section title="Station events" subtitle="Live feed from /ws/station" sx={{ flex: 1 }}>
          {events.length === 0 ? (
            <EmptyState message="Waiting for events…" />
          ) : (
            <Box sx={{ maxHeight: 360, overflow: "auto" }}>
              <Stack spacing={0.75}>
                {events.map((e, i) => (
                  <Stack key={i} direction="row" spacing={1} alignItems="center"
                    sx={{ py: 0.5, borderBottom: "1px solid", borderColor: "divider" }}>
                    <StatusDot kind={eventKind(e.type)} />
                    <Typography variant="caption" color="text.secondary" sx={{ fontFamily: MONO_STACK, minWidth: 64 }}>
                      {fmtTime(e.ts)}
                    </Typography>
                    <Typography variant="body2" fontWeight={600} sx={{ minWidth: 110 }}>{e.type}</Typography>
                    <Typography variant="caption" color="text.secondary"
                      sx={{ fontFamily: MONO_STACK, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {JSON.stringify(e.payload ?? {})}
                    </Typography>
                  </Stack>
                ))}
              </Stack>
            </Box>
          )}
        </Section>
      </Stack>
    </Box>
  );
}
