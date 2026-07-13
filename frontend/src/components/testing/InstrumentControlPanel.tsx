import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert, Box, Button, MenuItem, Stack, TextField, Typography,
} from "@mui/material";

import { api } from "../../api/client";
import { EmptyState, Section, StatusChip } from "../ui";
import { MONO_STACK } from "../../theme/theme";

/** Instrument Test Bench panel — a capability-driven manual control surface for
 * Python-owned library instruments. The backend capability catalog
 * (GET /variables/capabilities) decides which control renders per method; every
 * command goes through POST /variables/instances/{id}/call, the same guarded path
 * (lock + fail-fast + timeout + auto-diagnostics) recipes use. No per-instrument
 * UI code. Python-owned instruments are driven directly by the app, so there is NO
 * maintenance-mode gate here (maintenance is a LabVIEW-owned concept); commands are
 * enabled whenever the instrument is connected. Access is gated by the
 * HEALTH.MAINTENANCE permission on the route + endpoint. */

type ArgType = "number" | "int" | "bool" | "enum";
interface Arg { name: string; type: ArgType; unit?: string; options?: string[] }
interface MethodSpec {
  method: string;
  kind: "set" | "toggle" | "enum" | "read" | "action";
  label: string;
  args: Arg[];
  unit?: string;
  severity?: "warning" | "error";
}
interface Instance { id: string; library?: string; capabilities?: string[]; state: string; simulated?: boolean }

const fmtVal = (v: unknown): string => {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(3);
  return String(v);
};

export function InstrumentControlPanel({
  embedded = false,
}: { embedded?: boolean }) {
  const [configInsts, setConfigInsts] = useState<any[]>([]);   // /config/instruments (source of truth)
  const [engine, setEngine] = useState<Instance[]>([]);        // /variables/instances (live state)
  const [caps, setCaps] = useState<Record<string, { label: string; methods: MethodSpec[] }>>({});
  const [baseActions, setBaseActions] = useState<MethodSpec[]>([]);
  const [libs, setLibs] = useState<any[]>([]);
  const [sel, setSel] = useState("");
  const [argVals, setArgVals] = useState<Record<string, Record<string, string>>>({});
  const [readings, setReadings] = useState<Record<string, { value: unknown; ts: number }>>({});
  const [error, setError] = useState<string | null>(null);
  const [poll, setPoll] = useState(false);

  const refreshInstances = useCallback(() => {
    api.get("/config/instruments").then((r) => setConfigInsts(r || [])).catch(() => {});
    api.get("/variables/instances").then((r) => setEngine(r || [])).catch(() => {});
  }, []);

  useEffect(() => {
    refreshInstances();
    api.get("/variables/capabilities")
      .then((r) => { setCaps(r.capabilities || {}); setBaseActions(r.base_actions || []); })
      .catch(() => {});
    api.get("/variables/libraries").then((r) => setLibs(r.libraries || [])).catch(() => {});
  }, [refreshInstances]);

  // The Test Bench lists exactly the Instruments-config page's Python-owned
  // instruments; the variable engine (built at startup) supplies live state. An
  // instrument configured after boot shows as "not loaded" until a restart.
  const instances = useMemo(() => {
    const byId: Record<string, Instance> = Object.fromEntries(engine.map((e) => [e.id, e]));
    return (configInsts || [])
      .filter((c) => c.owner === "python" && c.enabled !== false)
      .map((c) => {
        const e = byId[c.id];
        return {
          id: c.id,
          label: c.label || c.id,
          library: c.library,
          simulated: c.simulated,
          capabilities: (e?.capabilities?.length ? e.capabilities
            : libs.find((l) => l.library_id === c.library)?.capabilities) || [],
          state: e ? e.state : "not loaded",
          loaded: !!e,
        };
      });
  }, [configInsts, engine, libs]);

  const inst = instances.find((i) => i.id === sel) || null;

  // default selection: first connected instance
  useEffect(() => {
    if (!sel && instances.length) {
      setSel((instances.find((i) => i.state === "connected") || instances[0]).id);
    }
  }, [instances, sel]);

  const capIds: string[] = inst?.capabilities || [];
  const groups = capIds.map((cid) => ({ id: cid, cap: caps[cid] })).filter((g) => g.cap);
  const connected = inst?.state === "connected";
  const canCommand = connected;   // python-owned: no maintenance-mode gate

  const setArg = (method: string, name: string, v: string) =>
    setArgVals((p) => ({ ...p, [method]: { ...(p[method] || {}), [name]: v } }));

  const buildArgs = (m: MethodSpec): any[] =>
    m.args.map((a) => {
      const raw = argVals[m.method]?.[a.name];
      if (a.type === "bool") return raw === "true";
      if (a.type === "int") return parseInt(raw ?? "", 10);
      if (a.type === "number") return Number(raw);
      return raw ?? a.options?.[0]; // enum
    });

  const call = useCallback(async (id: string, method: string, args: any[]): Promise<any> => {
    return api.post(`/variables/instances/${id}/call`, { method, args });
  }, []);

  const doRead = async (m: MethodSpec) => {
    if (!inst) return;
    try {
      const r = await call(inst.id, m.method, buildArgs(m));
      setReadings((p) => ({ ...p, [m.method]: { value: r.result, ts: Date.now() } }));
      setError(null);
    } catch (e: any) { setError(e.message); }
  };

  const command = async (method: string, args: any[]) => {
    if (!inst) return;
    try { await call(inst.id, method, args); setError(null); }
    catch (e: any) { setError(e.message); }
  };

  // auto-poll: only no-arg reads, across every declared capability
  const pollables = useMemo(() => {
    const out: MethodSpec[] = [];
    for (const cid of (inst?.capabilities || []))
      for (const m of (caps[cid]?.methods || []))
        if (m.kind === "read" && m.args.length === 0) out.push(m);
    return out;
  }, [inst, caps]);
  useEffect(() => {
    if (!poll || !connected || !inst) return;
    let alive = true;
    const tick = async () => {
      for (const m of pollables) {
        if (!alive) break;
        try {
          const r = await call(inst.id, m.method, []);
          if (alive) setReadings((p) => ({ ...p, [m.method]: { value: r.result, ts: Date.now() } }));
        } catch { /* transient — keep polling */ }
      }
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => { alive = false; clearInterval(id); };
  }, [poll, connected, pollables, inst, call]);

  const argInputs = (m: MethodSpec) => m.args.map((a) => (
    a.type === "bool" ? (
      <TextField key={a.name} select size="small" label={a.name} sx={{ width: 110 }}
        value={argVals[m.method]?.[a.name] ?? "true"}
        onChange={(e) => setArg(m.method, a.name, e.target.value)}>
        <MenuItem value="true">true</MenuItem>
        <MenuItem value="false">false</MenuItem>
      </TextField>
    ) : a.type === "enum" ? (
      <TextField key={a.name} select size="small" label={a.name} sx={{ width: 120 }}
        value={argVals[m.method]?.[a.name] ?? a.options?.[0] ?? ""}
        onChange={(e) => setArg(m.method, a.name, e.target.value)}>
        {(a.options || []).map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
      </TextField>
    ) : (
      <TextField key={a.name} size="small" type="number"
        label={a.unit ? `${a.name} (${a.unit})` : a.name} sx={{ width: 140 }}
        value={argVals[m.method]?.[a.name] ?? ""}
        onChange={(e) => setArg(m.method, a.name, e.target.value)} />
    )
  ));

  const methodRow = (m: MethodSpec) => (
    <Stack key={m.method} direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
      <Typography variant="body2" sx={{ minWidth: 150 }}>{m.label}</Typography>
      {m.kind === "read" ? (
        <>
          {argInputs(m)}
          <Button size="small" variant="outlined" disabled={!connected} onClick={() => doRead(m)}>Read</Button>
          <Typography sx={{ fontFamily: MONO_STACK, fontSize: 18, fontWeight: 600, minWidth: 90 }}>
            {fmtVal(readings[m.method]?.value)}
            {m.unit && readings[m.method] && <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 0.5 }}>{m.unit}</Typography>}
          </Typography>
        </>
      ) : m.kind === "toggle" ? (
        <>
          <Button size="small" variant="contained" color="success" disabled={!canCommand}
            onClick={() => command(m.method, [true])}>On</Button>
          <Button size="small" variant="outlined" color="inherit" disabled={!canCommand}
            onClick={() => command(m.method, [false])}>Off</Button>
        </>
      ) : (
        <>
          {argInputs(m)}
          <Button size="small" variant="contained" disabled={!canCommand}
            onClick={() => command(m.method, buildArgs(m))}>Apply</Button>
        </>
      )}
    </Stack>
  );

  return (
    <Box>
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}

      <Section title="Instrument" subtitle="Python-owned instruments from Config → Instruments"
        sx={{ mb: 2 }}
        actions={
          <Stack direction="row" spacing={1}>
            {inst && pollables.length > 0 && (
              <Button size="small" variant={poll ? "contained" : "outlined"} color="inherit"
                disabled={!connected} onClick={() => setPoll((p) => !p)}>
                {poll ? "Stop auto-poll" : "Auto-poll"}
              </Button>
            )}
            <Button size="small" variant="outlined" color="inherit" onClick={refreshInstances}>Refresh</Button>
          </Stack>
        }>
        {instances.length === 0 ? (
          <EmptyState message="No Python-owned instruments configured. Add one in Config → Instruments." />
        ) : (
          <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap>
            <TextField select size="small" label="instrument" value={sel}
              onChange={(e) => { setSel(e.target.value); setReadings({}); setPoll(false); }}
              sx={{ minWidth: 220 }}>
              {instances.map((i) => (
                <MenuItem key={i.id} value={i.id}>{i.label}{i.simulated ? " · sim" : ""}</MenuItem>
              ))}
            </TextField>
            {inst && <StatusChip label={inst.state} />}
            {inst && <Typography variant="body2" color="text.secondary">
              {capIds.map((c) => caps[c]?.label ?? c).join(" · ") || "unknown capability"}{inst.library ? ` · ${inst.library}` : ""}
            </Typography>}
          </Stack>
        )}
        {inst && !inst.loaded && (
          <Alert severity="warning" sx={{ mt: 1.5, py: 0 }}>
            Configured but not loaded into the engine — restart the app to load it.
          </Alert>
        )}
        {inst && inst.loaded && !connected && (
          <Alert severity="warning" sx={{ mt: 1.5, py: 0 }}>Instrument is {inst.state} — commands are disabled.</Alert>
        )}
      </Section>

      {inst && groups.length > 0 && (
        <Stack spacing={2}>
          {/* one control group per declared capability (composite = several) */}
          {groups.map(({ id, cap }) => (
            <Section key={id} title={cap.label}
              subtitle={capIds.length > 1 ? `capability · ${id}` : undefined}>
              <Stack spacing={1.25}>
                {cap.methods.map(methodRow)}
              </Stack>
            </Section>
          ))}
          <Section title="Safety" subtitle="available on any connected instrument">
            <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
              {baseActions.map((b) => (
                <Button key={b.method} variant="outlined"
                  color={b.severity === "error" ? "error" : "warning"}
                  disabled={!connected} onClick={() => command(b.method, [])}>
                  {b.label}
                </Button>
              ))}
            </Stack>
          </Section>
        </Stack>
      )}

      {inst && groups.length === 0 && capIds.length > 0 && (
        <Section title="Manual control"><EmptyState message={`No manual controls for '${capIds.join(", ")}'.`} /></Section>
      )}
      {!embedded && instances.length > 0 && !inst && (
        <Section title="Manual control"><EmptyState message="Select an instrument to begin." /></Section>
      )}
    </Box>
  );
}
