/** Station configuration (Settings). Sets the number of test sockets (st1..stN) and which
 * controller serves them — external LabVIEW, or the bundled Python controller that the app
 * auto-starts. Both are boot config (app.json): saving takes effect on the next restart, so
 * the section offers a Relaunch button. super_admin only (SYSTEM.SETTINGS). */
import { RestartAlt, Save } from "@mui/icons-material";
import {
  Alert, Button, MenuItem, Stack, TextField, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { Section, StatusChip } from "../../components/ui";

interface StationCfg {
  station_count?: number;
  configured_stations?: string[];
  running_stations?: string[];
  max_stations?: number | null;
  controller?: { kind?: "labview" | "python"; simulation?: boolean };
  restart_required?: boolean;
}

export function StationConfig() {
  const [cfg, setCfg] = useState<StationCfg>({});
  const [count, setCount] = useState<number>(1);
  const [kind, setKind] = useState<"labview" | "python">("labview");
  const [sim, setSim] = useState<boolean>(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = (d: StationCfg) => {
    setCfg(d);
    setCount(d.station_count ?? 1);
    setKind(d.controller?.kind ?? "labview");
    setSim(d.controller?.simulation ?? true);
  };

  useEffect(() => {
    api.get("/system/station-config").then(load).catch((e) => setError(e.message));
  }, []);

  const cap = cfg.max_stations ?? null;                 // null = uncapped
  const restart = cfg.restart_required
    || count !== (cfg.station_count ?? 1)
    || kind !== (cfg.controller?.kind ?? "labview");

  const save = async () => {
    setBusy(true); setError(null); setNotice(null);
    try {
      const d = await api.put("/system/station-config",
        { station_count: count, controller_kind: kind, simulation: sim });
      load(d);
      setNotice("Saved to app.json. Relaunch the station to apply.");
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  const relaunch = async () => {
    setBusy(true); setError(null);
    try {
      await api.post("/system/relaunch", {});
      setNotice("Station is relaunching — this page will reconnect in a few seconds.");
    } catch { /* backend exits mid-request */ }
    finally { setBusy(false); }
  };

  return (
    <Section title="Station configuration"
      subtitle="Test sockets and the controller that serves them — applied on restart">
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}
      <Stack spacing={2}>
        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="center">
          <TextField label="Test sockets" type="number" value={count} sx={{ width: 150 }}
            onChange={(e) => setCount(Math.max(1, Number(e.target.value) || 1))}
            inputProps={{ min: 1, max: cap ?? undefined, "aria-label": "test sockets" }} />
          <Typography variant="body2" color="text.secondary">
            {cap == null ? "no license cap" : `licensed max: ${cap}`}
            {" · "}running now: {(cfg.running_stations ?? []).length} ({(cfg.running_stations ?? []).join(", ") || "—"})
          </Typography>
        </Stack>

        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="center">
          <TextField select label="Controller" value={kind} sx={{ width: 260 }}
            onChange={(e) => setKind(e.target.value as "labview" | "python")}
            inputProps={{ "aria-label": "controller" }}>
            <MenuItem value="labview">LabVIEW (external engine)</MenuItem>
            <MenuItem value="python">Python (auto-started with the app)</MenuItem>
          </TextField>
          {kind === "python" && (
            <TextField select label="Mode" value={sim ? "sim" : "hw"} sx={{ width: 200 }}
              onChange={(e) => setSim(e.target.value === "sim")}
              inputProps={{ "aria-label": "controller mode" }}>
              <MenuItem value="sim">Simulation (no hardware)</MenuItem>
              <MenuItem value="hw">Hardware</MenuItem>
            </TextField>
          )}
        </Stack>

        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <Button variant="contained" startIcon={<Save />} disabled={busy} onClick={save}>Save</Button>
          <Button variant="outlined" color="warning" startIcon={<RestartAlt />} disabled={busy} onClick={relaunch}>
            Relaunch to apply
          </Button>
          {restart && <StatusChip label="restart required" kind="fail" />}
        </Stack>

        <Typography variant="caption" color="text.secondary">
          Sockets are named st1…stN. One socket runs as a single-station system (no station picker
          in the UI). Python controller starts and stops with the app; LabVIEW runs externally.
          Changes are written to app.json and take effect after a relaunch.
        </Typography>
      </Stack>
    </Section>
  );
}
