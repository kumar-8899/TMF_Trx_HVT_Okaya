/** Barcode config — total length, named parts (fixed-width slices), and which part is
 * the recipe id. Drives the Start dialog directly: enabled -> operator sees a serial/
 * barcode field (recipe auto-resolved from the recipe-id part); disabled -> a recipe
 * dropdown (manual pick). No manual mode switch — this flag is the only thing that
 * decides which one the operator sees. */
import { Add, DeleteOutline, Save } from "@mui/icons-material";
import {
  Alert, Box, Button, FormControlLabel, IconButton, Radio, Stack, Switch,
  Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { PageHeader, Section } from "../../components/ui";

interface Part { name: string; start: number; length: number }

export function ConfigBarcode() {
  const { can } = useAuth();
  const edit = can("CONFIG.EDIT");
  const [enabled, setEnabled] = useState(false);
  const [length, setLength] = useState(0);
  const [parts, setParts] = useState<Part[]>([]);
  const [recipePart, setRecipePart] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = () => {
    api.get("/config/barcode").then((c) => {
      setEnabled(c.enabled); setLength(c.length || 0); setParts(c.parts || []);
      setRecipePart(c.recipe_part || null); setDirty(false);
    }).catch((e) => setError(e.message));
  };
  useEffect(load, []);

  const mut = (fn: (p: Part[]) => Part[]) => { setParts((p) => fn(p)); setDirty(true); };
  const add = () => mut((p) => [...p, { name: `part_${p.length + 1}`, start: 0, length: 1 }]);
  const remove = (i: number) => {
    const removedName = parts[i]?.name;
    mut((p) => p.filter((_, j) => j !== i));
    if (removedName && removedName === recipePart) { setRecipePart(null); setDirty(true); }
  };
  const setField = (i: number, k: keyof Part, v: string) =>
    mut((p) => p.map((x, j) => (j === i ? { ...x, [k]: k === "name" ? v : Number(v) } : x)));

  const save = async () => {
    setBusy(true); setError(null); setNotice(null);
    try {
      await api.put("/config/barcode", { enabled, length, parts, recipe_part: recipePart });
      setNotice("Saved. The Start dialog now reflects this configuration.");
      load();
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Box>
      <PageHeader title="Barcode" subtitle="Barcode structure + recipe-id extraction for the Start dialog"
        actions={edit && <Button variant="contained" startIcon={<Save />} disabled={busy || !dirty} onClick={save}>Save</Button>} />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}

      <Stack spacing={2}>
        <Section>
          <Stack direction="row" spacing={3} alignItems="center" flexWrap="wrap" useFlexGap>
            <FormControlLabel control={<Switch checked={enabled} disabled={!edit}
              onChange={(e) => { setEnabled(e.target.checked); setDirty(true); }} />}
              label={<Box><Typography variant="subtitle2">Barcode enabled</Typography>
                <Typography variant="body2" color="text.secondary">
                  When on, the Start dialog shows a serial/barcode field and resolves the
                  recipe automatically. When off, it shows a recipe dropdown instead.
                </Typography></Box>} />
            <TextField label="Total length" type="number" size="small" sx={{ width: 140 }}
              value={length} disabled={!edit}
              onChange={(e) => { setLength(Number(e.target.value)); setDirty(true); }}
              inputProps={{ min: 1, "aria-label": "barcode_length" }} />
          </Stack>
        </Section>

        <Section title="Parts" subtitle="Named fixed-width slices of the barcode (0-based start + length); one is the recipe id" bodyPad={0}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell sx={{ width: 110 }}>Start</TableCell>
                <TableCell sx={{ width: 110 }}>Length</TableCell>
                <TableCell sx={{ width: 90 }}>Recipe ID</TableCell>
                {edit && <TableCell sx={{ width: 48 }} />}
              </TableRow>
            </TableHead>
            <TableBody>
              {parts.length === 0 ? (
                <TableRow><TableCell colSpan={5} sx={{ color: "text.secondary" }}>No parts. Add one.</TableCell></TableRow>
              ) : parts.map((p, i) => (
                <TableRow key={i}>
                  <TableCell>
                    <TextField fullWidth variant="standard" value={p.name} disabled={!edit}
                      onChange={(e) => setField(i, "name", e.target.value)} inputProps={{ "aria-label": `part_name_${i}` }} />
                  </TableCell>
                  <TableCell>
                    <TextField type="number" variant="standard" value={p.start} disabled={!edit}
                      onChange={(e) => setField(i, "start", e.target.value)} inputProps={{ min: 0, "aria-label": `part_start_${i}` }} />
                  </TableCell>
                  <TableCell>
                    <TextField type="number" variant="standard" value={p.length} disabled={!edit}
                      onChange={(e) => setField(i, "length", e.target.value)} inputProps={{ min: 1, "aria-label": `part_length_${i}` }} />
                  </TableCell>
                  <TableCell>
                    <Radio checked={!!p.name && recipePart === p.name} disabled={!edit || !p.name}
                      onChange={() => { setRecipePart(p.name); setDirty(true); }}
                      inputProps={{ "aria-label": `part_is_recipe_${i}` }} />
                  </TableCell>
                  {edit && <TableCell><IconButton size="small" onClick={() => remove(i)}><DeleteOutline fontSize="small" /></IconButton></TableCell>}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {edit && <Box sx={{ p: 1.5 }}><Button size="small" startIcon={<Add />} onClick={add}>Add part</Button></Box>}
        </Section>
      </Stack>
    </Box>
  );
}
