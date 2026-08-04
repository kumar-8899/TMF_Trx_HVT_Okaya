/** Variable Map — bind physical-parameter names to instrument signals (super_admin).
 *
 * The variable engine names scalar signals so recipes reference names, never hardware
 * (a vendor swap is one binding edit, zero recipe changes). This editor is the UI over
 * that map: pick a live instrument, and its declared *capabilities* drive which read /
 * setpoint methods a variable may bind (GET /variables/bindable/{id}) — the library is
 * the source of truth, so nothing is free-typed. Bindings are DB-backed and hot-applied
 * to the running engine (no restart). app.json-declared bindings show read-only. */
import { Add, DeleteOutline, MemoryOutlined } from "@mui/icons-material";
import {
  Alert, Box, Button, Chip, Divider, IconButton, MenuItem, Paper,
  Stack, TextField, Tooltip, Typography,
} from "@mui/material";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import { StationPicker } from "../../components/StationPicker";
import { EmptyState, PageHeader, Section, StatusChip, type StatusKind } from "../../components/ui";
import { MONO_STACK } from "../../theme/theme";

interface Arg { name: string; type: string; unit?: string }
interface Method { capability: string; method: string; label: string; unit?: string; fixed_args: Arg[] }
interface Bindable { instance: string; capabilities: string[]; read: Method[]; write: Method[] }
interface Binding {
  name: string; instance: string; read?: string | null; write?: string | null;
  args: any[]; units?: string | null; scale?: { gain: number; offset: number } | null;
  clamp?: { min?: number; max?: number } | null; editable: boolean; bound: boolean;
}
interface Draft {
  name: string; instance: string; read: string; write: string; args: any[];
  units: string; gain: string; offset: string; cmin: string; cmax: string;
}

const INSTANCE_KIND: Record<string, StatusKind> = {
  connected: "pass", faulted: "fail", reconnecting: "running", connecting: "running",
  disconnected: "idle", skipped: "idle",
};

const blank = (instance: string): Draft => ({
  name: "", instance, read: "", write: "", args: [], units: "", gain: "", offset: "", cmin: "", cmax: "",
});

const toDraft = (b: Binding): Draft => ({
  name: b.name, instance: b.instance, read: b.read ?? "", write: b.write ?? "",
  args: [...(b.args ?? [])], units: b.units ?? "",
  gain: b.scale?.gain != null ? String(b.scale.gain) : "",
  offset: b.scale?.offset != null ? String(b.scale.offset) : "",
  cmin: b.clamp?.min != null ? String(b.clamp.min) : "",
  cmax: b.clamp?.max != null ? String(b.clamp.max) : "",
});

export function ConfigVariableMap() {
  const [instances, setInstances] = useState<any[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [station, setStation] = useState<string | null>(null);   // multi-socket: which map
  const [bindable, setBindable] = useState<Bindable | null>(null);
  const [bindings, setBindings] = useState<Binding[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const stationQ = station ? `?station=${encodeURIComponent(station)}` : "";
  const refresh = useCallback(() => {
    api.get("/variables/instances").then(setInstances).catch((e) => setError(e.message));
    api.get(`/variables/bindings${station ? `?station=${encodeURIComponent(station)}` : ""}`)
      .then(setBindings).catch((e) => setError(e.message));
  }, [station]);
  useEffect(refresh, [refresh]);

  const selectInstance = (id: string) => {
    setSelected(id); setDraft(null); setError(null); setNotice(null); setBindable(null);
    api.get(`/variables/bindable/${id}`).then(setBindable).catch((e) => setError(e.message));
  };

  const rowsFor = useMemo(
    () => bindings.filter((b) => b.instance === selected),
    [bindings, selected]);

  // fixed args come from whichever method the draft binds (read + write share them)
  const method = useMemo<Method | null>(() => {
    if (!bindable || !draft) return null;
    return bindable.read.find((m) => m.method === draft.read)
      || bindable.write.find((m) => m.method === draft.write) || null;
  }, [bindable, draft]);
  const fixedArgs = method?.fixed_args ?? [];

  const preview = useMemo(() => {
    if (!draft) return "";
    const call = (m: string) => m ? `${draft.instance}.${m}(${(draft.args ?? []).join(", ")})` : "";
    return [draft.read && `read ${call(draft.read)}`, draft.write && `write ${call(draft.write)}`]
      .filter(Boolean).join("   ·   ");
  }, [draft]);

  const openNew = () => { if (selected) { setDraft(blank(selected)); setIsNew(true); setError(null); setNotice(null); } };
  const openEdit = (b: Binding) => {
    if (b.instance !== selected) selectInstance(b.instance);
    setDraft(toDraft(b)); setIsNew(false); setError(null); setNotice(null);
  };
  const setD = (k: keyof Draft, v: any) => setDraft((d) => (d ? { ...d, [k]: v } : d));
  const setArg = (i: number, v: any) => setDraft((d) => {
    if (!d) return d; const args = [...d.args]; args[i] = v; return { ...d, args };
  });

  const editable = draft ? (isNew || (rowsFor.find((b) => b.name === draft.name)?.editable ?? false)) : false;

  const save = async () => {
    if (!draft) return;
    setBusy(true); setError(null); setNotice(null);
    const body: any = {
      name: draft.name, instance: draft.instance, station: station || undefined,
      read: draft.read || undefined, write: draft.write || undefined,
      args: fixedArgs.map((_, i) => draft.args[i]),
      units: draft.units || undefined,
    };
    if (draft.gain !== "" || draft.offset !== "") body.scale = { gain: draft.gain || 1, offset: draft.offset || 0 };
    if (draft.cmin !== "" || draft.cmax !== "") body.clamp = { min: draft.cmin || undefined, max: draft.cmax || undefined };
    try {
      if (isNew) await api.post("/variables/bindings", body);
      else await api.put(`/variables/bindings/${draft.name}${stationQ}`, body);
      setNotice(`Saved '${draft.name}' — applied live.`); setDraft(null); refresh();
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!draft || isNew) return;
    setBusy(true); setError(null);
    try { await api.del(`/variables/bindings/${draft.name}${stationQ}`); setDraft(null); refresh(); }
    catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Box>
      <PageHeader title="Variable Map"
        subtitle="Map project parameters to instrument signals — the recipe/analytics naming layer"
        actions={<StationPicker value={station} onChange={(s) => { setStation(s); setDraft(null); }} />} />
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}

      <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems="stretch">
        {/* left: instances */}
        <Paper sx={{ width: { xs: "100%", md: 260 }, flexShrink: 0, overflow: "hidden" }}>
          <Box sx={{ bgcolor: "sectionHeader", color: "onNavy", px: 1.5, py: 1.25 }}>
            <Typography variant="subtitle2" sx={{ color: "onNavy" }}>Instruments ({instances.length})</Typography>
          </Box>
          {instances.length === 0 ? (
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", p: 2, textAlign: "center" }}>
              No Python-owned instances. Add a library instrument under Config → Instruments, then restart.
            </Typography>
          ) : instances.map((s) => (
            <Box key={s.id} onClick={() => selectInstance(s.id)} sx={{
              px: 1.5, py: 1, cursor: "pointer", display: "flex", alignItems: "center", gap: 1,
              borderLeft: "3px solid", borderLeftColor: selected === s.id ? "primary.main" : "transparent",
              "&:hover": { bgcolor: "action.hover" },
            }}>
              <MemoryOutlined fontSize="small" sx={{ color: "text.secondary" }} />
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Typography variant="body2" noWrap sx={{ fontWeight: 600, fontFamily: MONO_STACK }}>{s.id}</Typography>
                <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block" }}>
                  {(s.capabilities || []).join(", ") || "—"}
                </Typography>
              </Box>
              <StatusChip label={s.state} kind={INSTANCE_KIND[s.state] ?? "idle"} />
            </Box>
          ))}
        </Paper>

        {/* right: bindings on the instance + editor */}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {!selected ? <Section><EmptyState message="Select an instrument to map its signals." /></Section> : (
            <Stack spacing={2}>
              <Section title={`Variables on ${selected}`}
                subtitle={bindable ? bindable.capabilities.join(", ") : "loading…"}>
                {rowsFor.length === 0 ? (
                  <Typography variant="body2" color="text.secondary">No variables bound yet.</Typography>
                ) : (
                  <Stack spacing={0.5}>
                    {rowsFor.map((b) => (
                      <Stack key={b.name} direction="row" spacing={1} alignItems="center"
                        onClick={() => openEdit(b)} sx={{ cursor: "pointer", py: 0.5, "&:hover": { bgcolor: "action.hover" } }}>
                        <Typography variant="body2" sx={{ fontFamily: MONO_STACK, minWidth: 160, fontWeight: 600 }}>{b.name}</Typography>
                        <Typography variant="caption" color="text.secondary" sx={{ flex: 1 }}>
                          {[b.read && `R:${b.read}`, b.write && `W:${b.write}`].filter(Boolean).join(" ")}
                          {b.args?.length ? ` (${b.args.join(",")})` : ""}{b.units ? ` · ${b.units}` : ""}
                        </Typography>
                        {!b.editable && <Chip size="small" label="app.json" variant="outlined" />}
                        {!b.bound && <Chip size="small" color="warning" label="unbound" />}
                      </Stack>
                    ))}
                  </Stack>
                )}
                <Divider sx={{ my: 1.5 }} />
                <Button size="small" startIcon={<Add />} onClick={openNew} disabled={!bindable}>Add variable</Button>
              </Section>

              {draft && (
                <Section title={isNew ? "New variable" : draft.name}
                  subtitle={editable ? undefined : "read-only (declared in app.json)"}>
                  <Stack spacing={2}>
                    <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                      <TextField label="Name" value={draft.name} sx={{ width: 220 }}
                        disabled={!editable || !isNew} onChange={(e) => setD("name", e.target.value)}
                        helperText={isNew ? "lowercase, e.g. cell_voltage" : "immutable"}
                        inputProps={{ "aria-label": "variable_name" }} />
                      <TextField label="Units" value={draft.units} sx={{ width: 120 }} disabled={!editable}
                        onChange={(e) => setD("units", e.target.value)} placeholder={method?.unit ?? ""} />
                    </Stack>

                    <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                      <TextField select label="Read signal" value={draft.read} sx={{ width: 240 }} disabled={!editable}
                        onChange={(e) => setD("read", e.target.value)} inputProps={{ "aria-label": "read_method" }}>
                        <MenuItem value=""><em>none</em></MenuItem>
                        {(bindable?.read ?? []).map((m) => (
                          <MenuItem key={m.method} value={m.method}>{m.label} — {m.method}</MenuItem>
                        ))}
                      </TextField>
                      <TextField select label="Write setpoint" value={draft.write} sx={{ width: 240 }} disabled={!editable}
                        onChange={(e) => setD("write", e.target.value)} inputProps={{ "aria-label": "write_method" }}>
                        <MenuItem value=""><em>none</em></MenuItem>
                        {(bindable?.write ?? []).map((m) => (
                          <MenuItem key={m.method} value={m.method}>{m.label} — {m.method}</MenuItem>
                        ))}
                      </TextField>
                    </Stack>

                    {fixedArgs.length > 0 && (
                      <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                        {fixedArgs.map((a, i) => (
                          <TextField key={a.name} label={a.name + (a.unit ? ` (${a.unit})` : "")} sx={{ width: 160 }}
                            disabled={!editable} type={a.type === "number" || a.type === "int" ? "number" : "text"}
                            value={draft.args[i] ?? ""} onChange={(e) => setArg(i, e.target.value)}
                            helperText={`fixed ${a.type} arg`} />
                        ))}
                      </Stack>
                    )}

                    <Box>
                      <Typography variant="caption" color="text.secondary">Resolves to</Typography>
                      <Typography sx={{ fontFamily: MONO_STACK }}>{preview || "—"}</Typography>
                    </Box>

                    <Divider textAlign="left"><Typography variant="caption" color="text.secondary">Scale &amp; clamp (optional)</Typography></Divider>
                    <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                      <TextField label="Gain" value={draft.gain} sx={{ width: 110 }} type="number" disabled={!editable}
                        onChange={(e) => setD("gain", e.target.value)} placeholder="1.0" />
                      <TextField label="Offset" value={draft.offset} sx={{ width: 110 }} type="number" disabled={!editable}
                        onChange={(e) => setD("offset", e.target.value)} placeholder="0.0" />
                      <TextField label="Clamp min" value={draft.cmin} sx={{ width: 120 }} type="number" disabled={!editable}
                        onChange={(e) => setD("cmin", e.target.value)} />
                      <TextField label="Clamp max" value={draft.cmax} sx={{ width: 120 }} type="number" disabled={!editable}
                        onChange={(e) => setD("cmax", e.target.value)} />
                    </Stack>
                    <Typography variant="caption" color="text.secondary">
                      value = raw × gain + offset. Writes are clamped to [min, max]. Non-scalar controls (toggles,
                      enums, multiplexer, scope) are on the Test Bench, not here.
                    </Typography>

                    {editable && (
                      <Stack direction="row" spacing={1}>
                        <Button variant="contained" onClick={save}
                          disabled={busy || !draft.name || (!draft.read && !draft.write)}>
                          {isNew ? "Create" : "Save"}
                        </Button>
                        <Button onClick={() => setDraft(null)} disabled={busy}>Cancel</Button>
                        {!isNew && (
                          <Tooltip title="Delete binding">
                            <IconButton color="error" disabled={busy} onClick={remove}><DeleteOutline /></IconButton>
                          </Tooltip>
                        )}
                      </Stack>
                    )}
                  </Stack>
                </Section>
              )}
            </Stack>
          )}
        </Box>
      </Stack>
    </Box>
  );
}
