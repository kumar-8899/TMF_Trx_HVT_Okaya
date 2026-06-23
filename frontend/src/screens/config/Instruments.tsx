/** Instrument configuration — a transport-driven form engine.
 *
 * One generic form renders ANY transport from the backend catalog
 * (GET /config/transports): each transport declares typed fields, so adding a new
 * instrument type later is a backend catalog entry, not new UI. LabVIEW owns the
 * actual I/O; here we capture the connection profile and ask LabVIEW to probe it. */
import { Add, DeleteOutline, MemoryOutlined, WifiTethering } from "@mui/icons-material";
import {
  Alert, Box, Button, Chip, Divider, FormControlLabel, IconButton, MenuItem, Paper,
  Stack, Switch, TextField, Tooltip, Typography,
} from "@mui/material";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { EmptyState, PageHeader, Section, StatusChip, type StatusKind } from "../../components/ui";
import { MONO_STACK } from "../../theme/theme";

interface Field { key: string; label: string; type: string; required: boolean; default?: any; placeholder?: string; help?: string; options?: string[] }
interface Transport { id: string; label: string; address_template: string; fields: Field[] }
interface Instrument {
  id: string; label: string; model?: string; transport: string; params: Record<string, any>;
  address?: string; family?: string; capabilities?: string[]; enabled?: boolean;
}

const TEST_KIND: Record<string, StatusKind> = { pass: "pass", fail: "fail", timeout: "fail", error: "fail", unavailable: "running" };
const blank = (): Instrument => ({ id: "", label: "", model: "", transport: "", params: {}, family: "", capabilities: [], enabled: true });

export function ConfigInstruments() {
  const { can } = useAuth();
  const edit = can("CONFIG.EDIT");
  const [transports, setTransports] = useState<Transport[]>([]);
  const [list, setList] = useState<Instrument[]>([]);
  const [draft, setDraft] = useState<Instrument | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [test, setTest] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.get("/config/instruments").then(setList).catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    api.get("/config/transports").then(setTransports).catch((e) => setError(e.message));
    refresh();
  }, [refresh]);

  const transport = useMemo(() => transports.find((t) => t.id === draft?.transport) || null, [transports, draft]);

  const open = (inst: Instrument | null) => {
    setError(null); setNotice(null); setTest(null);
    if (inst) { setDraft({ ...inst, params: { ...inst.params } }); setIsNew(false); }
    else { setDraft(blank()); setIsNew(true); }
  };
  const setF = (k: keyof Instrument, v: any) => setDraft((d) => (d ? { ...d, [k]: v } : d));
  const setParam = (k: string, v: any) => setDraft((d) => (d ? { ...d, params: { ...d.params, [k]: v } } : d));
  const pickTransport = (id: string) => {
    const t = transports.find((x) => x.id === id);
    const params: Record<string, any> = {};
    t?.fields.forEach((f) => { if (f.default != null) params[f.key] = f.default; });
    setDraft((d) => (d ? { ...d, transport: id, params } : d));
    setTest(null);
  };

  // live preview of the canonical resource string (mirrors the backend template)
  const addressPreview = useMemo(() => {
    if (!transport) return "";
    return transport.address_template.replace(/\{(\w+)\}/g, (_, k) => String(draft?.params?.[k] ?? "")).trim();
  }, [transport, draft]);

  const save = async () => {
    if (!draft) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      if (isNew) await api.post("/config/instruments", draft);
      else await api.put(`/config/instruments/${draft.id}`, draft);
      setNotice(`Saved ${draft.id}.`); setIsNew(false); refresh();
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!draft || isNew) return;
    setBusy(true); setError(null);
    try { await api.del(`/config/instruments/${draft.id}`); setDraft(null); refresh(); }
    catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };
  const runTest = async () => {
    if (!draft) return;
    setBusy(true); setError(null); setTest(null);
    try { setTest(await api.post("/config/instruments/test", { transport: draft.transport, params: draft.params })); }
    catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Box>
      <PageHeader title="Instruments" subtitle="Connection profiles — the device specifics are handled by LabVIEW"
        actions={edit && <Button variant="contained" startIcon={<Add />} onClick={() => open(null)}>Add instrument</Button>} />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}

      <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems="stretch">
        {/* left: instrument list */}
        <Paper sx={{ width: { xs: "100%", md: 300 }, flexShrink: 0, overflow: "hidden" }}>
          <Box sx={{ bgcolor: "sectionHeader", color: "onNavy", px: 1.5, py: 1.25 }}>
            <Typography variant="subtitle2" sx={{ color: "onNavy" }}>Instruments ({list.length})</Typography>
          </Box>
          {list.length === 0 ? <Typography variant="caption" color="text.secondary" sx={{ display: "block", p: 2, textAlign: "center" }}>No instruments yet.</Typography>
            : list.map((inst) => (
              <Box key={inst.id} onClick={() => open(inst)} sx={{
                px: 1.5, py: 1, cursor: "pointer", display: "flex", alignItems: "center", gap: 1,
                borderLeft: "3px solid", borderLeftColor: draft?.id === inst.id && !isNew ? "primary.main" : "transparent",
                opacity: inst.enabled === false ? 0.5 : 1, "&:hover": { bgcolor: "action.hover" },
              }}>
                <MemoryOutlined fontSize="small" sx={{ color: "text.secondary" }} />
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Typography variant="body2" noWrap sx={{ fontWeight: 600 }}>{inst.label || inst.id}</Typography>
                  <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block", fontFamily: MONO_STACK }}>
                    {inst.transport} · {inst.id}
                  </Typography>
                </Box>
              </Box>
            ))}
        </Paper>

        {/* right: editor */}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {!draft ? <Section><EmptyState message="Select an instrument, or add one." /></Section> : (
            <Stack spacing={2}>
              <Section title={isNew ? "New instrument" : draft.label || draft.id}>
                <Stack spacing={2}>
                  <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                    <TextField label="ID" value={draft.id} sx={{ width: 180 }} disabled={!edit || !isNew}
                      onChange={(e) => setF("id", e.target.value)} helperText={isNew ? "lowercase, immutable" : "immutable"}
                      inputProps={{ "aria-label": "instrument_id" }} />
                    <TextField label="Label" value={draft.label} sx={{ flex: 1, minWidth: 180 }} disabled={!edit}
                      onChange={(e) => setF("label", e.target.value)} />
                    <TextField label="Model" value={draft.model ?? ""} sx={{ width: 180 }} disabled={!edit}
                      onChange={(e) => setF("model", e.target.value)} />
                  </Stack>
                  <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="center">
                    <TextField select label="Transport" value={draft.transport} sx={{ width: 220 }} disabled={!edit}
                      onChange={(e) => pickTransport(e.target.value)} inputProps={{ "aria-label": "transport" }}>
                      <MenuItem value=""><em>select…</em></MenuItem>
                      {transports.map((t) => <MenuItem key={t.id} value={t.id}>{t.label}</MenuItem>)}
                    </TextField>
                    <FormControlLabel control={<Switch checked={draft.enabled !== false} disabled={!edit}
                      onChange={(e) => setF("enabled", e.target.checked)} />} label="Enabled" />
                  </Stack>
                </Stack>
              </Section>

              {transport && (
                <Section title="Connection" subtitle={transport.label}>
                  <Stack spacing={2}>
                    <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                      {transport.fields.map((f) => (
                        f.type === "select" ? (
                          <TextField key={f.key} select label={f.label} sx={{ width: 200 }} disabled={!edit}
                            value={draft.params[f.key] ?? f.default ?? ""} helperText={f.help}
                            onChange={(e) => setParam(f.key, e.target.value)}>
                            {(f.options ?? []).map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
                          </TextField>
                        ) : (
                          <TextField key={f.key} label={f.label + (f.required ? " *" : "")} sx={{ width: 220 }} disabled={!edit}
                            type={f.type === "number" ? "number" : f.type === "password" ? "password" : "text"}
                            value={draft.params[f.key] ?? ""} placeholder={f.placeholder} helperText={f.help}
                            onChange={(e) => setParam(f.key, f.type === "number" ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value)} />
                        )
                      ))}
                    </Stack>
                    <Box>
                      <Typography variant="caption" color="text.secondary">Resource preview</Typography>
                      <Typography sx={{ fontFamily: MONO_STACK }}>{addressPreview || "—"}</Typography>
                    </Box>
                    <Divider />
                    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                      <Button variant="outlined" startIcon={<WifiTethering />} disabled={busy || !draft.transport} onClick={runTest}>
                        Test connection
                      </Button>
                      {test && <StatusChip label={test.status} kind={TEST_KIND[test.status] ?? "idle"} />}
                      {test && <Typography variant="body2" color="text.secondary">{test.detail}{test.identity ? ` · ${test.identity}` : ""}</Typography>}
                    </Stack>
                  </Stack>
                </Section>
              )}

              <Section title="Health linkage" subtitle="Used to template hardware health checks">
                <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                  <TextField label="Family" value={draft.family ?? ""} sx={{ width: 200 }} disabled={!edit}
                    onChange={(e) => setF("family", e.target.value)} helperText="e.g. dmm, psu, scope" />
                  <TextField label="Capabilities" value={(draft.capabilities ?? []).join(", ")} sx={{ flex: 1, minWidth: 200 }} disabled={!edit}
                    onChange={(e) => setF("capabilities", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
                    helperText="comma-separated, e.g. measure_v, source_i" />
                </Stack>
                {(draft.capabilities ?? []).length > 0 && (
                  <Stack direction="row" spacing={0.5} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
                    {draft.capabilities!.map((c) => <Chip key={c} size="small" label={c} />)}
                  </Stack>
                )}
              </Section>

              {edit && (
                <Stack direction="row" spacing={1}>
                  <Button variant="contained" disabled={busy || !draft.id || !draft.transport} onClick={save}>
                    {isNew ? "Create" : "Save"}
                  </Button>
                  {!isNew && (
                    <Tooltip title="Delete instrument">
                      <IconButton color="error" disabled={busy} onClick={remove}><DeleteOutline /></IconButton>
                    </Tooltip>
                  )}
                </Stack>
              )}
            </Stack>
          )}
        </Box>
      </Stack>
    </Box>
  );
}
