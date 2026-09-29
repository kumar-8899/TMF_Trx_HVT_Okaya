import {
  Alert, Button, Chip, CircularProgress, Divider, Stack, Table, TableBody, TableCell,
  TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { Section, StatusChip } from "../../components/ui";
import { MONO_STACK } from "../../theme/theme";

/** Settings → Updates (UPDATES.md items 5-9). Discovery is notify-only; installing is
 * two deliberate clicks — **Download** (fetch + verify + offer) then **Install** (stage) —
 * and the launcher swaps the artifact on relaunch. Rollback reverts to a local backup
 * (last-known-good by default). An update is a risk to a running line, so nothing here is
 * automatic. super_admin only (SYSTEM.SETTINGS-gated on the edge). */
export function UpdatesConfig() {
  const [current, setCurrent] = useState<any>(null);
  const [offers, setOffers] = useState<any[]>([]);
  const [source, setSource] = useState<string | null>(null);
  const [stationMode, setStationMode] = useState<"online" | "air_gapped">("online");
  const [available, setAvailable] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [path, setPath] = useState("");
  const [zipPath, setZipPath] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reconnecting, setReconnecting] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const r = await api.get("/update/offers");
      setCurrent(r.current); setOffers(r.offers || []); setSource(r.source || null);
      setStationMode(r.station_mode === "air_gapped" ? "air_gapped" : "online");
      setStatus(await api.get("/update/status"));
    } catch (e: any) { setError(e.message); }
  };
  useEffect(() => { refresh(); }, []);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(null); setMsg(null);
    try { await fn(); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };

  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  /** After a relaunch/rollback the backend exits (~0.6s later) and the launcher swaps + boots
   * the new build. Poll /healthz until it answers again, then re-fetch so the page shows the
   * post-relaunch state instead of sitting on the stale pre-relaunch view. Times out at ~90s
   * (the update system's BOOT_TIMEOUT convention) → "reload manually". */
  const awaitRelaunch = async (what: string) => {
    setReconnecting(`Station is ${what} — waiting for it to come back…`);
    await sleep(3000);                                  // let the process actually exit first
    const deadline = Date.now() + 90_000;
    while (Date.now() < deadline) {
      try {
        await api.get("/healthz", { auth: false });     // public; back up once this resolves
        setReconnecting(null);
        await refresh();
        setMsg(`Station is back up — ${what} finished.`);
        return;
      } catch {
        await sleep(2000);
      }
    }
    setReconnecting(null);
    throw new Error(
      "The station has not come back after 90 seconds. If it is a windowed station, it may need "
      + "to be reopened; otherwise reload this page once it has restarted.");
  };

  const check = () => run(async () => {
    const r = await api.post("/update/check", {});
    // The backend is network-tolerant: a failed check (no network, or a private repo rejecting an
    // empty/invalid token) still returns 200 with `error` set and `available: null` — NOT an
    // exception, so it doesn't land in the catch below. Surface it as a distinct failure instead of
    // silently falling through to "up to date", which looked identical and hid real breakage.
    if (r.error) {
      setAvailable(null);
      setError(`Update check failed: ${r.error} — verify updates.github_repo / github_token `
        + "(or TMF_UPDATE_TOKEN) if this is a private repo, and that this station has network access.");
      return;
    }
    setAvailable(r.available);
    setMsg(r.available ? `Update available: ${r.available.tag}` : "No update available — you are up to date.");
  });
  const download = () => run(async () => {
    const r = await api.post("/update/download", {});
    setMsg(r.idempotent ? `Already downloaded ${r.version}.` : `Downloaded ${r.track} ${r.version} — review below, then Install.`);
    setAvailable(null); await refresh();
  });
  const ingest = () => run(async () => {
    const r = await api.post("/update/ingest", { bundle_path: path });
    setMsg(`Ingested ${r.track} ${r.version} — ${r.verdict?.reason}`); await refresh();
  });
  const installFile = () => run(async () => {
    const r = await api.post("/update/install-file", { ksupdate_path: path, zip_path: zipPath });
    setMsg(r.staged_dir
      ? `Staged ${r.track} ${r.version} from file — review below, then Install.`
      : `Offered ${r.track} ${r.version} — ${r.verdict?.reason}`);
    await refresh();
  });
  const scanIncoming = () => run(async () => {
    const r = await api.post("/update/scan-incoming", {});
    const found: any[] = r.found || [];
    const ok = found.filter((f) => !f.error);
    const failed = found.filter((f) => f.error);
    await refresh();
    if (found.length === 0) {
      setMsg("No update files found — nothing has been copied to this station yet.");
      return;
    }
    const summary = ok.map((f) => `${f.track} ${f.version} (${f.scope})`).join(", ");
    setMsg(ok.length
      ? `Staged from local files: ${summary} — review below, then Install.`
      : "Found update files, but none could be staged.");
    if (failed.length) {
      setError(failed.map((f) => `${f.slot}: ${f.error}`).join(" · "));
    }
  });
  const install = (id: string) => run(async () => {
    const r = await api.post(`/update/apply/${id}`, {}); setMsg(r.note || "Staged."); await refresh();
  });
  const relaunch = (id: string) => run(async () => {
    await api.post(`/update/relaunch/${id}`, {});
    await awaitRelaunch("relaunching to apply the update");
  });
  const rollback = (target: string) => run(async () => {
    await api.post("/update/rollback", { target });
    await awaitRelaunch("relaunching to roll back");
  });

  return (
    <Section title="Updates" subtitle="signed application updates (Keystation) — notify-only, two-click install">
      {error && <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setError(null)}>{error}</Alert>}
      {msg && <Alert severity="info" sx={{ mb: 1.5 }} onClose={() => setMsg(null)}>{msg}</Alert>}
      {reconnecting && (
        <Alert severity="info" icon={<CircularProgress size={18} />} sx={{ mb: 1.5 }}>
          {reconnecting}
        </Alert>
      )}
      {status?.swap_error && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          The last relaunch could <b>not</b> apply {status.swap_error.version ?? "the update"} —
          the previous version is still running (attempt {status.swap_error.strikes}).
          <Typography variant="caption" display="block" sx={{ mt: 0.5, fontFamily: MONO_STACK }}>
            {status.swap_error.error}
          </Typography>
          <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
            Retry with <b>Relaunch</b> below; if it keeps failing, roll back and reinstall, or check
            <code> data/launcher.log</code> on the station.
          </Typography>
        </Alert>
      )}

      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Installed:{" "}
        {current?.app_version
          ? <>Application <b style={{ fontFamily: MONO_STACK }}>{current.app_version}</b> · framework <b style={{ fontFamily: MONO_STACK }}>{current.version}</b></>
          : <>framework <b style={{ fontFamily: MONO_STACK }}>{current?.version ?? "—"}</b> <i>(no app payload)</i></>}
        {current?.abi >= 0 && <> · core ABI {current.abi}</>}
      </Typography>

      {stationMode === "air_gapped" ? (
        <Alert severity="info" sx={{ mb: 1.5 }}>
          This station is <b>air-gapped</b> (<code>updates.station_mode</code>). Online check /
          download is disabled — update from USB using <b>Install from file</b> below.
        </Alert>
      ) : (
        <>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 0.5 }}>
            <Button variant="contained" disabled={!source || busy} onClick={check}>Check for application updates</Button>
            {source && <Typography variant="caption" color="text.secondary">source: {source}</Typography>}
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ mb: 1.5, display: "block" }}>
            Checks this application's releases only (its own version line) — not the framework. The
            framework version is provenance; it changes only when a new app build is built on a newer one.
          </Typography>

          {available && (
            <Alert severity="success" sx={{ mb: 2 }}
              action={<Button color="inherit" size="small" disabled={busy} onClick={download}>Download</Button>}>
              <b>{available.tag}</b> available{available.asset_bytes ? ` · ${Math.round(available.asset_bytes / 1024)} KB` : ""}
              {available.notes && <Typography variant="caption" display="block" sx={{ mt: 0.5, whiteSpace: "pre-wrap" }}>{available.notes}</Typography>}
            </Alert>
          )}
        </>
      )}

      {offers.length > 0 && (
        <Table size="small" sx={{ mb: 2 }}>
          <TableHead><TableRow>
            <TableCell>Track</TableCell><TableCell>Version</TableCell><TableCell>Trust</TableCell>
            <TableCell>Verdict</TableCell><TableCell>Status</TableCell><TableCell align="right">Action</TableCell>
          </TableRow></TableHead>
          <TableBody>
            {offers.map((o) => (
              <TableRow key={o.release_id}>
                <TableCell>{o.track}</TableCell>
                <TableCell sx={{ fontFamily: MONO_STACK }}>{o.version}{o.criticality ? ` · ${o.criticality}` : ""}</TableCell>
                <TableCell>{o.status === "verify_failed"
                  ? <Chip size="small" color="error" label="verify failed" />
                  : o.verified ? <Chip size="small" color="success" label="signed" /> : <Chip size="small" color="warning" label="unverified" />}</TableCell>
                <TableCell>
                  <StatusChip label={o.verdict?.applicable ? "applicable" : "no"} kind={o.verdict?.applicable ? "pass" : "idle"} />
                  <Typography variant="caption" color="text.secondary" display="block">{o.verdict?.reason}</Typography>
                </TableCell>
                <TableCell>{o.status}</TableCell>
                <TableCell align="right">
                  {o.status === "apply_pending" || o.status === "relaunch_requested"
                    ? <Button size="small" color="warning" variant="contained" disabled={busy} onClick={() => relaunch(o.release_id)}>Relaunch</Button>
                    : <Button size="small" variant="outlined" disabled={busy || !o.verdict?.applicable} onClick={() => install(o.release_id)}>Install</Button>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {/* Rollback / backups */}
      {status?.backups?.length > 0 && (
        <>
          <Divider sx={{ my: 1.5 }} />
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="subtitle2">Installed builds (rollback)</Typography>
            <Button size="small" color="warning" variant="outlined" disabled={busy || !status.last_known_good}
              onClick={() => rollback("last_known_good")}>Roll back to last known good</Button>
          </Stack>
          <Table size="small">
            <TableBody>
              {status.backups.map((b: any) => (
                <TableRow key={b.id}>
                  <TableCell sx={{ fontFamily: MONO_STACK }}>{b.version ?? "—"}
                    {b.last_known_good && <Chip size="small" color="success" label="last known good" sx={{ ml: 1 }} />}</TableCell>
                  <TableCell sx={{ fontFamily: MONO_STACK, color: "text.secondary" }}>{b.id}</TableCell>
                  <TableCell align="right">
                    <Button size="small" variant="outlined" disabled={busy} onClick={() => rollback(b.id)}>Roll back</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}

      <Divider sx={{ my: 1.5 }} />
      <Typography variant="subtitle2" sx={{ mb: 1 }}>Install from file (USB / air-gapped)</Typography>
      {stationMode === "online" ? (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
          This station updates <b>online</b> (<code>updates.station_mode</code>) — install-from-file
          is disabled; use the check button above. Set{" "}
          <code>updates.station_mode: "air_gapped"</code> in <code>app.json</code> for a bench with no
          internet.
        </Typography>
      ) : (
        <>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
            <Button variant="contained" disabled={busy} onClick={scanIncoming}>Scan for updates on this PC</Button>
            <Typography variant="caption" color="text.secondary">
              Ran the update delivery tool (the .exe from IT/support)? Click this — no paths to type.
            </Typography>
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ mb: 1.5, display: "block" }}>
            Same signature + hash verification and swap/rollback as everything else here — this just
            looks in the two fixed spots the delivery tool drops files into instead of asking you to
            browse for them.
          </Typography>
          <Divider sx={{ my: 1.5 }} />
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
            Advanced: point directly at a <b>.ksupdate</b> + <b>.zip</b> pair copied anywhere else (USB,
            a network share):
          </Typography>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <TextField size="small" label=".ksupdate path" value={path}
              onChange={(e) => setPath(e.target.value)} sx={{ minWidth: 300 }} />
            <TextField size="small" label="artifact .zip path" value={zipPath}
              onChange={(e) => setZipPath(e.target.value)} sx={{ minWidth: 300 }} />
            <Button variant="outlined" disabled={!path || !zipPath || busy} onClick={installFile}>Stage from file</Button>
            <Button variant="text" disabled={!path || busy} onClick={ingest}>Verify only</Button>
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1.5, display: "block" }}>
            Either way: Install + Relaunch the staged offer above. The launcher swaps the artifact on
            the next restart and auto-reverts to last-known-good if the new build won't boot.
          </Typography>
        </>
      )}
    </Section>
  );
}
