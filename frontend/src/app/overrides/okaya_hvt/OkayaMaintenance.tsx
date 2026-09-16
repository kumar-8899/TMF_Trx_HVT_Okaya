/** Okaya HVT Testbench — Maintenance override (app-owned screen override, TEMPLATE.md §1.3 /
 * §1). Replaces the framework's generic Maintenance Console with bench-specific manual
 * controls: every relay1/relay2 channel from `maps/st1.json`, plus a manual hipot AC-withstand
 * test (route + voltage + test time -> one "Start Test" button that energises the route, runs
 * the test, and always de-energises the route again — same safety pattern as the `hipot_acw`
 * step type and `app/okaya_hvt/tools/probe_hipot_acw.py`).
 *
 * Everything here goes through `POST /variables/instances/{id}/call` (`write_digital` on
 * relay1/relay2, `measure_acw` on hipot) — the SAME instance registry `probe_relay.py`/
 * `probe_hipot_acw.py` drive directly, already proven live against real hardware. It does NOT
 * use the named-signal path (`GET/PUT /variables/{name}/value`): that reads from the backend's
 * own separate variable-engine bindings (`self.engine.maps`), which are populated from
 * `app.json`'s static `variables` config or DB-authored bindings — NOT from `maps/st1.json`
 * (only the standalone Python controller reads that file directly, for recipe execution). No
 * bindings are authored for this app, so `GET /variables` returns `[]` here; that's why the
 * channel numbers below are a hardcoded mirror of `maps/st1.json`'s relay1/relay2 entries
 * rather than fetched — keep them in sync if the map changes.
 *
 * `/variables/instances/{id}/call` is super_admin-only (`backend/modules/variables/api.py`
 * `_TESTBENCH`), so this whole page is gated the same way, matching how the framework's own
 * Maintenance Console already gates its Instrument Test Bench panel.
 *
 * Relay1 (the six hipot routes) is treated as ONE-CHANNEL-AT-A-TIME here: energising any relay1
 * channel — by hand or via Start Test — first de-energises whichever relay1 channel was already
 * on. Relay2 (tower lights) has no such restriction; multiple lamps/buzzer can be on together.
 */
import { Bolt, PlayArrow } from "@mui/icons-material";
import {
  Alert, Box, Button, Grid, MenuItem, Stack, TextField, Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";

import { api } from "../../../api/client";
import { useAuth } from "../../../auth/AuthContext";
import { EmptyState, PageHeader, Section, StatusChip } from "../../../components/ui";
import { HIPOT_TESTS } from "./HipotRecipeForm";

interface InstanceStatus { id: string; state: string; simulated?: boolean }

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// Mirrors maps/st1.json — see the file docstring above for why this isn't fetched.
const ROUTE_CHANNELS: Record<string, number> = {
  hipot_route_pri_sec: 0, hipot_route_pri_core: 1, hipot_route_sec_core: 2,
  hipot_route_fb_core: 3, hipot_route_pri_fb: 4, hipot_route_sec_fb: 5,
};
const RELAY2_CHANNELS: { channel: number; name: string; label: string }[] = [
  { channel: 0, name: "tl_red", label: "Red lamp" },
  { channel: 1, name: "tl_green", label: "Green lamp" },
  { channel: 2, name: "buzzer", label: "Buzzer" },
];

export function OkayaMaintenance() {
  const { principal } = useAuth();
  const authorized = principal?.role === "super_admin";

  const [instances, setInstances] = useState<Record<string, InstanceStatus>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [relay1On, setRelay1On] = useState<string | null>(null);
  const [relay2State, setRelay2State] = useState<Record<string, boolean>>({});

  const [route, setRoute] = useState(HIPOT_TESTS[0].routeSignal);
  const [kv, setKv] = useState("0.5");
  const [testTimeS, setTestTimeS] = useState("10");
  const [step, setStep] = useState("1");
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  const [result, setResult] = useState<{ leakage_ma: number; breakdown: boolean } | null>(null);

  const load = useCallback(() => {
    api.get("/variables/instances")
      .then((rows: InstanceStatus[]) => setInstances(Object.fromEntries(rows.map((r) => [r.id, r]))))
      .catch((e: any) => setLoadError(e.message));
  }, []);
  useEffect(() => { load(); }, [load]);

  const connected = (id: string) => instances[id]?.state === "connected";
  const routeLabel = (name: string) => HIPOT_TESTS.find((t) => t.routeSignal === name)?.label ?? name;

  const call = async (instanceId: string, method: string, args: any[]) =>
    api.post(`/variables/instances/${instanceId}/call`, { method, args });

  // relay1: one channel at a time — energising a new one first opens whichever was on.
  const setRelay1Channel = async (routeSignal: string | null) => {
    if (relay1On && relay1On !== routeSignal) await call("relay1", "write_digital", [ROUTE_CHANNELS[relay1On], false]);
    if (routeSignal) await call("relay1", "write_digital", [ROUTE_CHANNELS[routeSignal], true]);
    setRelay1On(routeSignal);
  };

  const toggleRelay1 = async (routeSignal: string) => {
    setBusy(routeSignal); setActionError(null);
    try { await setRelay1Channel(relay1On === routeSignal ? null : routeSignal); }
    catch (e: any) { setActionError(e.message); }
    finally { setBusy(null); }
  };

  const toggleRelay2 = async (name: string, channel: number) => {
    setBusy(name); setActionError(null);
    const next = !relay2State[name];
    try { await call("relay2", "write_digital", [channel, next]); setRelay2State((p) => ({ ...p, [name]: next })); }
    catch (e: any) { setActionError(e.message); }
    finally { setBusy(null); }
  };

  const voltageV = Number(kv) * 1000;
  const dwellS = Number(testTimeS);
  const stepN = Number(step) || 1;
  const canStart = authorized && connected("hipot") && connected("relay1") && !testing
    && Number.isFinite(voltageV) && voltageV > 0 && Number.isFinite(dwellS) && dwellS > 0 && !!route;

  const startTest = async () => {
    setTesting(true); setTestError(null); setResult(null);
    let energised = false;
    try {
      await setRelay1Channel(route);
      energised = true;
      await sleep(200); // settle, matches hipot_acw step type's default settle_s
      const r = await call("hipot", "measure_acw", [voltageV, dwellS, stepN]);
      const [leakage_ma, breakdown] = r.result as [number, boolean];
      setResult({ leakage_ma, breakdown });
    } catch (e: any) {
      setTestError(e.message);
    } finally {
      if (energised) {
        try { await setRelay1Channel(null); }
        catch (e: any) { setTestError((prev) => `${prev ? prev + " | " : ""}failed to open route: ${e.message}`); }
      }
      setTesting(false);
    }
  };

  if (!authorized) {
    return (
      <Box>
        <PageHeader title="Maintenance — Okaya HVT Testbench" subtitle="Manual relay + hipot control" />
        <Section title="Restricted">
          <EmptyState message="Manual relay/hipot control requires the super_admin role." />
        </Section>
      </Box>
    );
  }

  return (
    <Box>
      <PageHeader title="Maintenance — Okaya HVT Testbench" subtitle="Manual relay + hipot control" />
      {loadError && <Alert severity="error" sx={{ mb: 2 }}>{loadError}</Alert>}
      {actionError && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setActionError(null)}>{actionError}</Alert>}

      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Section title="Relay 1 — hipot routes"
            subtitle="one channel at a time — energising a new route opens whichever was on"
            actions={<StatusChip label={connected("relay1")
              ? (relay1On ? `${routeLabel(relay1On)} energised` : "none energised")
              : (instances.relay1?.state ?? "unknown")}
              kind={!connected("relay1") ? "fail" : relay1On ? "running" : "idle"} />}>
            {!connected("relay1") && (
              <Alert severity="warning" sx={{ mb: 1.5, py: 0 }}>relay1 is not connected — controls disabled.</Alert>
            )}
            <Stack spacing={1}>
              {HIPOT_TESTS.map((t) => (
                <Stack key={t.routeSignal} direction="row" spacing={1.5} alignItems="center">
                  <Typography variant="body2" sx={{ minWidth: 190 }}>{t.label}</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ minWidth: 150, fontFamily: "monospace" }}>
                    {t.routeSignal} (ch{ROUTE_CHANNELS[t.routeSignal]})
                  </Typography>
                  <Button size="small" variant={relay1On === t.routeSignal ? "contained" : "outlined"}
                    color={relay1On === t.routeSignal ? "warning" : "inherit"}
                    disabled={!connected("relay1") || testing || busy === t.routeSignal}
                    onClick={() => toggleRelay1(t.routeSignal)}>
                    {relay1On === t.routeSignal ? "De-energise" : "Energise"}
                  </Button>
                </Stack>
              ))}
            </Stack>
          </Section>
        </Grid>

        <Grid item xs={12} md={6}>
          <Section title="Relay 2 — tower lights" subtitle="multiple can be on together"
            actions={<StatusChip label={instances.relay2?.state ?? "unknown"} kind={connected("relay2") ? "idle" : "fail"} />}>
            {!connected("relay2") && (
              <Alert severity="warning" sx={{ mb: 1.5, py: 0 }}>relay2 is not connected — controls disabled.</Alert>
            )}
            <Stack spacing={1}>
              {RELAY2_CHANNELS.map((r) => (
                <Stack key={r.name} direction="row" spacing={1.5} alignItems="center">
                  <Typography variant="body2" sx={{ minWidth: 190 }}>{r.label}</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ minWidth: 150, fontFamily: "monospace" }}>
                    {r.name} (ch{r.channel})
                  </Typography>
                  <Button size="small" variant={relay2State[r.name] ? "contained" : "outlined"}
                    color={relay2State[r.name] ? "success" : "inherit"}
                    disabled={!connected("relay2") || busy === r.name}
                    onClick={() => toggleRelay2(r.name, r.channel)}>
                    {relay2State[r.name] ? "On" : "Off"}
                  </Button>
                </Stack>
              ))}
            </Stack>
          </Section>
        </Grid>

        <Grid item xs={12}>
          <Section title="Hipot — manual AC-withstand test"
            subtitle="UT5320R+ · one route at a time · raw reading, no pass/fail limit applied"
            actions={<StatusChip label={instances.hipot?.state ?? "unknown"} kind={connected("hipot") ? "idle" : "fail"} />}>
            {!connected("hipot") && (
              <Alert severity="warning" sx={{ mb: 1.5, py: 0 }}>hipot is not connected — Start Test disabled.</Alert>
            )}
            <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
              <TextField select size="small" label="route" value={route} disabled={testing}
                onChange={(e) => setRoute(e.target.value)} sx={{ minWidth: 220 }}>
                {HIPOT_TESTS.map((t) => <MenuItem key={t.key} value={t.routeSignal}>{t.label}</MenuItem>)}
              </TextField>
              <TextField size="small" label="Voltage (kV)" type="number" value={kv} disabled={testing}
                onChange={(e) => setKv(e.target.value)} sx={{ width: 130 }} />
              <TextField size="small" label="Test time (s)" type="number" value={testTimeS} disabled={testing}
                onChange={(e) => setTestTimeS(e.target.value)} sx={{ width: 130 }} />
              <TextField size="small" label="Step" type="number" value={step} disabled={testing}
                onChange={(e) => setStep(e.target.value)} sx={{ width: 90 }} />
              <Button variant="contained" startIcon={testing ? <Bolt /> : <PlayArrow />}
                disabled={!canStart} onClick={startTest}>
                {testing ? "Testing…" : "Start Test"}
              </Button>
            </Stack>

            {testing && (
              <Alert severity="warning" sx={{ mb: 2 }}>
                {routeLabel(route)} energised — running {kv} kV / {testTimeS} s. Route opens
                automatically when the test finishes.
              </Alert>
            )}
            {testError && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setTestError(null)}>{testError}</Alert>}
            {result && !testing && (
              <Alert severity={result.breakdown ? "error" : "success"}>
                <strong>{routeLabel(route)}</strong>: leakage = {result.leakage_ma.toFixed(4)} mA
                {"  ·  "}breakdown = {String(result.breakdown)}
              </Alert>
            )}
          </Section>
        </Grid>
      </Grid>
    </Box>
  );
}
