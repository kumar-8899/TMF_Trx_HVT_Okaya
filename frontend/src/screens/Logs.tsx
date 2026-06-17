import {
  Box, Button, Drawer, IconButton, MenuItem, Stack, Tab, Table, TableBody, TableCell,
  TableHead, TableRow, Tabs, TextField, Typography,
} from "@mui/material";
import { Close } from "@mui/icons-material";
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import { EmptyState, PageHeader, Section, StatusChip, statusKind } from "../components/ui";
import { MONO_STACK } from "../theme/theme";

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
  const [selected, setSelected] = useState<Record_ | null>(null);
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
    <Box>
      <PageHeader title="Logs" subtitle="Error diagnostics and the action audit trail" />

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Errors" value="errors" />
        <Tab label="Actions" value="actions" />
      </Tabs>

      <Section sx={{ mb: 2 }}>
        <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap>
          {tab === "errors" ? (
            <>
              <TextField select label="Min level" value={level}
                onChange={(e) => setLevel(e.target.value)} sx={{ width: 150 }}
                inputProps={{ "aria-label": "level" }}>
                {LEVELS.map((l) => <MenuItem key={l} value={l}>{l || "(all)"}</MenuItem>)}
              </TextField>
              <TextField label="Subsystem" value={subsystem} onChange={(e) => setSubsystem(e.target.value)} />
            </>
          ) : (
            <>
              <TextField label="User" value={user} onChange={(e) => setUser(e.target.value)} />
              <TextField label="Action prefix" value={action} onChange={(e) => setAction(e.target.value)} />
            </>
          )}
          <Button variant="contained" onClick={() => load(true)}>Apply</Button>
        </Stack>
      </Section>

      {error && <Typography color="error" sx={{ mb: 2 }}>{error}</Typography>}

      <Section bodyPad={0}>
        {items.length === 0 ? (
          <EmptyState message="No records." />
        ) : (
          <Table>
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: 200 }}>Time</TableCell>
                {tab === "errors" ? <TableCell sx={{ width: 120 }}>Level</TableCell> : <TableCell sx={{ width: 140 }}>User</TableCell>}
                <TableCell>Summary</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {items.map((r) => (
                <TableRow key={r.id} hover sx={{ cursor: "pointer" }} onClick={() => setSelected(r)}>
                  <TableCell sx={{ fontFamily: MONO_STACK, color: "text.secondary", whiteSpace: "nowrap" }}>{fmt(r.ts)}</TableCell>
                  <TableCell>
                    {tab === "errors"
                      ? <StatusChip label={r.data.level} kind={statusKind(r.data.level)} />
                      : r.data.user}
                  </TableCell>
                  <TableCell>{r.summary}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>

      {cursor && (
        <Box sx={{ mt: 2 }}><Button variant="outlined" onClick={() => load(false)}>Load more</Button></Box>
      )}

      <Drawer anchor="right" open={Boolean(selected)} onClose={() => setSelected(null)}>
        <Box sx={{ width: 420, p: 2 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="h6">Record detail</Typography>
            <IconButton size="small" onClick={() => setSelected(null)} aria-label="close detail"><Close fontSize="small" /></IconButton>
          </Stack>
          {selected && (
            <>
              <Typography variant="caption" color="text.secondary">{fmt(selected.ts)}</Typography>
              <Typography sx={{ my: 1 }}>{selected.summary}</Typography>
              <Box component="pre" sx={{
                fontFamily: MONO_STACK, fontSize: 12, p: 1.5, borderRadius: 1, overflow: "auto",
                bgcolor: (t) => (t.palette.mode === "dark" ? "rgba(255,255,255,0.04)" : "rgba(2,6,23,0.04)"),
              }}>
                {JSON.stringify(selected.data, null, 2)}
              </Box>
            </>
          )}
        </Box>
      </Drawer>
    </Box>
  );
}
