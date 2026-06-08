import {
  Box, Button, Chip, MenuItem, Paper, Stack, Tab, Table, TableBody, TableCell,
  TableHead, TableRow, Tabs, TextField, Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";

type Tab = "errors" | "actions";

interface Record_ {
  id: string;
  ts: number;
  summary: string;
  data: Record<string, any>;
}

function qs(params: Record<string, unknown>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

const fmt = (ts: number) => new Date(ts * 1000).toLocaleString();
const LEVELS = ["", "warning", "error", "critical"];

export function Logs() {
  const [tab, setTab] = useState<Tab>("errors");
  const [items, setItems] = useState<Record_[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // error filters
  const [level, setLevel] = useState("");
  const [subsystem, setSubsystem] = useState("");
  // action filters
  const [user, setUser] = useState("");
  const [action, setAction] = useState("");

  const load = useCallback(async (reset: boolean) => {
    setError(null);
    try {
      const base = tab === "errors" ? "/logs/errors" : "/logs/actions";
      const params =
        tab === "errors"
          ? { level, subsystem, limit: 50, cursor: reset ? undefined : cursor }
          : { user, action, limit: 50, cursor: reset ? undefined : cursor };
      const page = await api.get(base + qs(params));
      setItems((prev) => (reset ? page.items : [...prev, ...page.items]));
      setCursor(page.next_cursor);
    } catch (e: any) {
      setError(e?.message || "Failed to load logs");
    }
  }, [tab, level, subsystem, user, action, cursor]);

  // Reload from the top whenever the tab changes.
  useEffect(() => {
    setItems([]);
    setCursor(null);
    load(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  return (
    <Stack spacing={2}>
      <Typography variant="h5">Logs</Typography>
      <Tabs value={tab} onChange={(_, v) => setTab(v)}>
        <Tab label="Errors" value="errors" />
        <Tab label="Actions" value="actions" />
      </Tabs>

      <Stack direction="row" spacing={2} alignItems="center">
        {tab === "errors" ? (
          <>
            <TextField select size="small" label="Min level" value={level}
              onChange={(e) => setLevel(e.target.value)} sx={{ width: 140 }}
              inputProps={{ "aria-label": "level" }}>
              {LEVELS.map((l) => <MenuItem key={l} value={l}>{l || "(all)"}</MenuItem>)}
            </TextField>
            <TextField size="small" label="Subsystem" value={subsystem}
              onChange={(e) => setSubsystem(e.target.value)} />
          </>
        ) : (
          <>
            <TextField size="small" label="User" value={user} onChange={(e) => setUser(e.target.value)} />
            <TextField size="small" label="Action prefix" value={action}
              onChange={(e) => setAction(e.target.value)} />
          </>
        )}
        <Button variant="outlined" onClick={() => load(true)}>Apply</Button>
      </Stack>

      {error && <Typography color="error">{error}</Typography>}

      <Paper>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Time</TableCell>
              {tab === "errors" ? <TableCell>Level</TableCell> : <TableCell>User</TableCell>}
              <TableCell>Summary</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {items.map((r) => (
              <TableRow key={r.id}>
                <TableCell>{fmt(r.ts)}</TableCell>
                <TableCell>
                  {tab === "errors"
                    ? <Chip size="small" label={r.data.level}
                        color={r.data.level === "critical" || r.data.level === "error" ? "error" : "warning"} />
                    : r.data.user}
                </TableCell>
                <TableCell>{r.summary}</TableCell>
              </TableRow>
            ))}
            {items.length === 0 && (
              <TableRow><TableCell colSpan={3}>No records.</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </Paper>

      {cursor && (
        <Box><Button onClick={() => load(false)}>Load more</Button></Box>
      )}
    </Stack>
  );
}
