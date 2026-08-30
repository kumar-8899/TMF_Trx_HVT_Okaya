/** Remote debugging (Settings). Turns the flight-recorder sidecar on/off and, when on,
 * exposes it to a developer's laptop (bind address + token) and toggles the rolling
 * disk recording. Written to app.json; applied on the next relaunch (station.py
 * supervises the sidecar). super_admin only (SYSTEM.SETTINGS). See docs/REMOTE_DEBUG.md. */
import { RestartAlt, Save } from "@mui/icons-material";
import {
  Alert, Button, FormControlLabel, Stack, Switch, TextField, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { Section, StatusChip } from "../../components/ui";

interface DebugCfg {
  enabled?: boolean;
  bind_host?: string;
  port?: number;
  remote?: boolean;
  has_token?: boolean;
  rolling_enabled?: boolean;
  running?: boolean;
  health?: { bytes_written_today?: number; rolling_dropped?: number; dropped?: number } | null;
  restart_required?: boolean;
}

export function DebugConfig() {
  const [cfg, setCfg] = useState<DebugCfg>({});
  const [enabled, setEnabled] = useState(false);
  const [bindHost, setBindHost] = useState("127.0.0.1");
  const [token, setToken] = useState("");
  const [rolling, setRolling] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = (d: DebugCfg) => {
    setCfg(d);
    setEnabled(Boolean(d.enabled));
    setBindHost(d.bind_host ?? "127.0.0.1");
    setRolling(d.rolling_enabled ?? true);
    setToken("");
  };

  useEffect(() => {
    api.get("/system/debug-config").then(load).catch((e) => setError(e.message));
  }, []);

  const restart = cfg.restart_required
    || enabled !== Boolean(cfg.enabled)
    || bindHost !== (cfg.bind_host ?? "127.0.0.1")
    || rolling !== (cfg.rolling_enabled ?? true)
    || token.length > 0;
  const remote = bindHost.trim() !== "" && !["127.0.0.1", "::1", "localhost"].includes(bindHost.trim());

  const save = async () => {
    setBusy(true); setError(null); setNotice(null);
    try {
      const body: any = { enabled, bind_host: bindHost.trim(), rolling_enabled: rolling };
      if (token) body.token = token;          // write-only; omit to keep the existing token
      const d = await api.put("/system/debug-config", body);
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

  const kb = cfg.health?.bytes_written_today != null
    ? `${Math.round((cfg.health.bytes_written_today / 1024))} KB today` : null;
  const drops = (cfg.health?.rolling_dropped ?? cfg.health?.dropped) || 0;

  return (
    <Section title="Remote debugging"
      subtitle="Record what the station does so faults can be diagnosed later — applied on restart">
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}
      <Stack spacing={2}>
        <FormControlLabel
          control={<Switch checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />}
          label={
            <Typography>Enable the flight recorder
              {" "}
              <StatusChip label={cfg.running ? "running" : "stopped"} kind={cfg.running ? "pass" : "idle"} />
              {enabled && kb && <Typography component="span" variant="caption" color="text.secondary">{"  ·  " + kb + (drops ? ` · ${drops} dropped` : "")}</Typography>}
            </Typography>
          } />

        {enabled && (
          <>
            <FormControlLabel
              control={<Switch checked={rolling} onChange={(e) => setRolling(e.target.checked)} />}
              label={<Typography variant="body2">Continuous recording to disk (survives unattended faults)</Typography>} />

            <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="flex-start">
              <TextField label="Access from" value={bindHost} sx={{ width: 220 }}
                onChange={(e) => setBindHost(e.target.value)}
                helperText="127.0.0.1 = this machine only. A LAN address lets a developer's laptop connect."
                inputProps={{ "aria-label": "bind host" }} />
              <TextField label={cfg.has_token ? "Access token (set — leave blank to keep)" : "Access token"}
                value={token} type="password" sx={{ width: 280 }}
                onChange={(e) => setToken(e.target.value)}
                error={remote && !cfg.has_token && !token}
                helperText={remote ? "Required to allow remote (non-loopback) access." : "Only needed for remote access."}
                inputProps={{ "aria-label": "debug token" }} />
            </Stack>
          </>
        )}

        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <Button variant="contained" startIcon={<Save />} disabled={busy} onClick={save}>Save</Button>
          <Button variant="outlined" color="warning" startIcon={<RestartAlt />} disabled={busy} onClick={relaunch}>
            Relaunch to apply
          </Button>
          {restart && <StatusChip label="restart required" kind="fail" />}
        </Stack>

        <Typography variant="caption" color="text.secondary">
          The recorder runs as a separate process on port {cfg.port ?? 8001}, so it keeps recording even if
          the app itself is restarting. Pull captures with the <b>tmf-debug</b> tool (docs/REMOTE_DEBUG.md).
          Leave “Access from” at 127.0.0.1 unless a developer needs to connect from another machine.
        </Typography>
      </Stack>
    </Section>
  );
}
