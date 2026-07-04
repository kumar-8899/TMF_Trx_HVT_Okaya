/** Shift config — configurable shift labels + start times (24h, contiguous).
 *
 * Locked model: shifts tile 24h — each runs to the next shift's start; the last
 * wraps past midnight. The business day rolls at the FIRST shift's start, so an
 * overnight shift belongs to the calendar date it started on. Reports stamp the
 * business day + shift for shift-aware analytics. */
import { Add, DeleteOutline, Save } from "@mui/icons-material";
import {
  Alert, Box, Button, Chip, FormControlLabel, IconButton, Stack, Switch,
  Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import { useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { PageHeader, Section } from "../../components/ui";
import { MONO_STACK } from "../../theme/theme";

interface Shift { label: string; start: string }

export function ConfigShift() {
  const { can } = useAuth();
  const edit = can("CONFIG.EDIT");
  const [enabled, setEnabled] = useState(false);
  const [shifts, setShifts] = useState<Shift[]>([]);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [current, setCurrent] = useState<any | null>(null);

  const load = () => {
    api.get("/config/shift").then((c) => { setEnabled(c.enabled); setShifts(c.shifts || []); setDirty(false); })
      .catch((e) => setError(e.message));
    api.get("/config/shift/current").then(setCurrent).catch(() => {});
  };
  useEffect(load, []);

  // ordered by start (the first is the day boundary); windows shown as start → next start
  const ordered = useMemo(
    () => [...shifts].sort((a, b) => (a.start || "").localeCompare(b.start || "")),
    [shifts],
  );
  const endOf = (i: number) => ordered[(i + 1) % ordered.length]?.start ?? "—";

  const mut = (fn: (s: Shift[]) => Shift[]) => { setShifts((s) => fn(s)); setDirty(true); };
  const add = () => mut((s) => [...s, { label: `Shift ${s.length + 1}`, start: "06:00" }]);
  const remove = (i: number) => mut((s) => s.filter((_, j) => j !== i));
  const setField = (i: number, k: keyof Shift, v: string) => mut((s) => s.map((x, j) => (j === i ? { ...x, [k]: v } : x)));

  const save = async () => {
    setBusy(true); setError(null); setNotice(null);
    try {
      await api.put("/config/shift", { enabled, shifts });
      setNotice("Saved. Business day + shift are stamped on new reports.");
      load();
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Box>
      <PageHeader title="Shifts" subtitle="Shift labels + timings drive the business day for analytics"
        actions={edit && <Button variant="contained" startIcon={<Save />} disabled={busy || !dirty} onClick={save}>Save</Button>} />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}

      <Stack spacing={2}>
        <Section>
          <Stack direction="row" spacing={3} alignItems="center" flexWrap="wrap" useFlexGap>
            <FormControlLabel control={<Switch checked={enabled} disabled={!edit}
              onChange={(e) => { setEnabled(e.target.checked); setDirty(true); }} />}
              label={<Box><Typography variant="subtitle2">Shifts enabled</Typography>
                <Typography variant="body2" color="text.secondary">When on, analytics count by <b>business day</b> (a shift can span midnight), not calendar date.</Typography></Box>} />
            {current?.enabled && (
              <Box>
                <Typography variant="caption" color="text.secondary" display="block">CURRENT</Typography>
                <Chip color="primary" label={`${current.shift_label} · ${current.business_day}`} sx={{ fontFamily: MONO_STACK }} />
              </Box>
            )}
          </Stack>
        </Section>

        <Section title="Shifts" subtitle="24h, contiguous — each runs until the next shift's start; the earliest is the day boundary" bodyPad={0}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Label</TableCell><TableCell sx={{ width: 130 }}>Start</TableCell>
                <TableCell sx={{ width: 110 }}>Ends (→)</TableCell>{edit && <TableCell sx={{ width: 48 }} />}
              </TableRow>
            </TableHead>
            <TableBody>
              {ordered.length === 0 ? (
                <TableRow><TableCell colSpan={4} sx={{ color: "text.secondary" }}>No shifts. Add one.</TableCell></TableRow>
              ) : ordered.map((s, i) => {
                const realIdx = shifts.indexOf(s);
                return (
                  <TableRow key={i}>
                    <TableCell>
                      <TextField fullWidth variant="standard" value={s.label} disabled={!edit}
                        onChange={(e) => setField(realIdx, "label", e.target.value)} inputProps={{ "aria-label": `shift_label_${i}` }} />
                    </TableCell>
                    <TableCell>
                      <TextField type="time" variant="standard" value={s.start} disabled={!edit}
                        onChange={(e) => setField(realIdx, "start", e.target.value)} inputProps={{ "aria-label": `shift_start_${i}` }} />
                    </TableCell>
                    <TableCell sx={{ fontFamily: MONO_STACK, color: "text.secondary" }}>{endOf(i)}{i === 0 ? " ·boundary" : ""}</TableCell>
                    {edit && <TableCell><IconButton size="small" onClick={() => remove(realIdx)}><DeleteOutline fontSize="small" /></IconButton></TableCell>}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          {edit && <Box sx={{ p: 1.5 }}><Button size="small" startIcon={<Add />} onClick={add}>Add shift</Button></Box>}
        </Section>
      </Stack>
    </Box>
  );
}
