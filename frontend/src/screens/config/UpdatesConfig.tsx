import {
  Alert, Button, Chip, Divider, Stack, Table, TableBody, TableCell, TableHead, TableRow,
  TextField, Typography,
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
  const [available, setAvailable] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [path, setPath] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      const r = await api.get("/update/offers");
      setCurrent(r.current); setOffers(r.offers || []); setSource(r.source || null);
      setStatus(await api.get("/update/status"));
    } catch (e: any) { setError(e.message); }
  };
  useEffect(() => { refresh(); }, []);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(null); setMsg(null);
    try { await fn(); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };

  const check = () => run(async () => {
    const r = await api.post("/update/check", {});
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
  const install = (id: string) => run(async () => {
    const r = await api.post(`/update/apply/${id}`, {}); setMsg(r.note || "Staged."); await refresh();
  });
  const relaunch = (id: string) => run(async () => {
    await api.post(`/update/relaunch/${id}`, {});
    setMsg("Station is relaunching to apply the update — this page will reconnect shortly.");
  });
  const rollback = (target: string) => run(async () => {
    await api.post("/update/rollback", { target });
    setMsg("Station is relaunching to roll back — this page will reconnect shortly.");
  });

  return (
    <Section title="Updates" subtitle="signed code updates (Keystation) — notify-only, two-click install">
      {error && <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setError(null)}>{error}</Alert>}
      {msg && <Alert severity="info" sx={{ mb: 1.5 }} onClose={() => setMsg(null)}>{msg}</Alert>}

      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Installed: <b style={{ fontFamily: MONO_STACK }}>{current?.app_version ? `App ${current.app_version}` : `framework ${current?.version ?? "—"}`}</b>
        {current?.app_version && <> · framework {current.version}</>}
        {current?.abi >= 0 && <> · core ABI {current.abi}</>}
      </Typography>

      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
        <Button variant="contained" disabled={!source || busy} onClick={check}>Check for updates</Button>
        {source && <Typography variant="caption" color="text.secondary">source: {source}</Typography>}
      </Stack>

      {available && (
        <Alert severity="success" sx={{ mb: 2 }}
          action={<Button color="inherit" size="small" disabled={busy} onClick={download}>Download</Button>}>
          <b>{available.tag}</b> available{available.asset_bytes ? ` · ${Math.round(available.asset_bytes / 1024)} KB` : ""}
          {available.notes && <Typography variant="caption" display="block" sx={{ mt: 0.5, whiteSpace: "pre-wrap" }}>{available.notes}</Typography>}
        </Alert>
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
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <TextField size="small" label="or ingest a .ksupdate path (airgap/USB)" value={path}
          onChange={(e) => setPath(e.target.value)} sx={{ minWidth: 320 }} />
        <Button variant="text" disabled={!path || busy} onClick={ingest}>Ingest file</Button>
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ mt: 1.5, display: "block" }}>
        Discovery only notifies — nothing downloads unasked. Install stages the release; the launcher
        swaps the artifact on the next restart and auto-reverts to last-known-good if the new build won't boot.
      </Typography>
    </Section>
  );
}
