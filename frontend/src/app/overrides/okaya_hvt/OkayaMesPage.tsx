/** MES (Okaya table) — the app-owned page for the `okaya_mes` module: write ONE wide row per finished run
 * into Okaya's legacy MES table (per-test min / max / actual / result, overall result, first failed test).
 * The framework MES page keeps its own (header-only) outbound OFF for this bench; this one is the writer.
 * A failure is loud: it stays in "Failed deliveries" (and the module reports DEGRADED health) until the
 * operator retries or dismisses it. Passwords never come back from the API: blank = keep the stored one. */
import Save from "@mui/icons-material/Save";
import WifiTethering from "@mui/icons-material/WifiTethering";
import {
  Alert, Box, Button, FormControlLabel, Stack, Switch, Table, TableBody, TableCell, TableHead, TableRow,
  TextField, Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";

import { api } from "../../../api/client";
import { DbServerForm, type ServerConn } from "../../../components/DbServerForm";
import { EmptyState, PageHeader, Section, StatusChip } from "../../../components/ui";
import { connBody, NameField, useListing } from "../../../screens/config/mes/common";
import { MONO_STACK } from "../../../theme/theme";

interface Cfg { enabled: boolean; station_name: string; database: string; table: string; connection: ServerConn }
const EMPTY: Cfg = { enabled: false, station_name: "HV Testing", database: "", table: "", connection: {} };

interface Alert_ { run_id: string; serial: string; result?: string; error: string; ts: number }

export function OkayaMesPage() {
  const [cfg, setCfg] = useState<Cfg>(EMPTY);
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState<any | null>(null);
  const [dirty, setDirty] = useState(false);
  const [test, setTest] = useState<any | null>(null);
  const [check, setCheck] = useState<any | null>(null);
  const [alerts, setAlerts] = useState<Alert_[]>([]);
  const [runId, setRunId] = useState("");
  const [preview, setPreview] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // 404 on the module's own API = the backend did not load `okaya_mes` (a station installed before the module existed
  // has no entry for it in its live config / license) — say so instead of a bare "Not Found".
  const [notLoaded, setNotLoaded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [c, s, a] = await Promise.all([api.get("/okaya-mes/config"), api.get("/okaya-mes/status"),
        api.get("/okaya-mes/alerts")]);
      setCfg({ ...EMPTY, ...c, connection: c.connection ?? {} });
      setStatus(s);
      setAlerts(a.items ?? []);
      setNotLoaded(false);
    } catch (e: any) {
      if (e?.status === 404) setNotLoaded(true); else setError(e.message);
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const conn = cfg.connection;
  const connReady = Boolean(conn.provider && (conn.provider === "sqlite" || conn.host));
  const body = () => ({ connection: connBody(conn, password) });
  const patch = (p: Partial<Cfg>) => { setCfg((x) => ({ ...x, ...p })); setDirty(true); setNotice(null); setCheck(null); };
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(null);
    try { await fn(); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };

  const dbs = useListing(connReady ? () => api.post("/okaya-mes/db/databases", body()) : null,
    [conn.provider, conn.host, conn.port, conn.user, conn.odbc_driver]);
  const tables = useListing(connReady && cfg.database
    ? () => api.post("/okaya-mes/db/tables", { ...body(), database: cfg.database }) : null,
    [conn.provider, conn.host, conn.port, conn.user, conn.odbc_driver, cfg.database]);

  const save = () => run(async () => {
    const saved = await api.put("/okaya-mes/config", {
      enabled: cfg.enabled, station_name: cfg.station_name, database: cfg.database, table: cfg.table,
      connection: connBody(conn, password) });
    setCfg({ ...EMPTY, ...saved, connection: saved.connection ?? {} });
    setPassword(""); setDirty(false); setNotice("Saved."); setStatus(await api.get("/okaya-mes/status"));
  });
  const toggle = (v: boolean) => run(async () => {
    const saved = await api.put("/okaya-mes/config", { enabled: v });
    setCfg((x) => ({ ...x, enabled: Boolean(saved.enabled) }));
    setStatus(await api.get("/okaya-mes/status"));
  });
  const runTest = () => run(async () => { setTest(await api.post("/okaya-mes/db/test", body())); dbs.reload(); });
  const tableBody = () => ({ ...body(), database: cfg.database, table: cfg.table });
  const runCheck = () => run(async () => { setCheck(await api.post("/okaya-mes/table/check", tableBody())); });
  const runCreate = () => run(async () => {
    setCheck(await api.post("/okaya-mes/table/create", tableBody())); tables.reload();
  });
  const retry = (id: string) => run(async () => {
    const r = await api.post(`/okaya-mes/alerts/${id}/retry`, {});
    setNotice(r.ok ? `Delivered: ${r.detail}` : `Still failing: ${r.detail}`); await refresh();
  });
  const dismiss = (id: string) => run(async () => { await api.post(`/okaya-mes/alerts/${id}/dismiss`, {}); await refresh(); });
  const doPreview = () => run(async () => { setPreview(await api.get(`/okaya-mes/preview/${encodeURIComponent(runId.trim())}`)); });
  const send = () => run(async () => {
    const r = await api.post(`/okaya-mes/runs/${encodeURIComponent(runId.trim())}/send`, {});
    setNotice(`Sent ${r.serial_no}: ${r.result}${r.failed_test ? ` (failed: ${r.failed_test})` : ""}`); await refresh();
  });

  if (notLoaded) {
    return (
      <Box>
        <PageHeader title="MES — Okaya table" subtitle="One wide row per finished run, written into Okaya's existing MES table" />
        <Alert severity="warning">
          <strong>The okaya_mes module is not loaded on this station.</strong> It is missing from this station&apos;s live
          configuration, so nothing can be saved or sent from here. Close the station, run{" "}
          <span style={{ fontFamily: MONO_STACK }}>app\okaya_hvt\tools\enable_okaya_mes.ps1 -InstallDir &quot;&lt;install folder&gt;&quot;</span>{" "}
          (it adds <span style={{ fontFamily: MONO_STACK }}>okaya_mes</span> to <span style={{ fontFamily: MONO_STACK }}>config\app.json</span> and{" "}
          <span style={{ fontFamily: MONO_STACK }}>config\license.json</span>, with backups), then start the station again.
        </Alert>
      </Box>
    );
  }

  return (
    <Box>
      <PageHeader title="MES — Okaya table"
        subtitle="One wide row per finished run, written into Okaya's existing MES table" />
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}

      {alerts.length > 0 && (
        <Section title={`Failed deliveries (${alerts.length})`}
          subtitle="These results did NOT reach the Okaya table — retry once the database is reachable">
          <Table size="small">
            <TableHead><TableRow><TableCell>Serial</TableCell><TableCell>Result</TableCell><TableCell>Error</TableCell>
              <TableCell align="right" /></TableRow></TableHead>
            <TableBody>
              {alerts.map((a) => (
                <TableRow key={a.run_id}>
                  <TableCell sx={{ fontFamily: MONO_STACK }}>{a.serial || a.run_id}</TableCell>
                  <TableCell>{a.result}</TableCell>
                  <TableCell>{a.error}</TableCell>
                  <TableCell align="right">
                    <Button size="small" disabled={busy} onClick={() => retry(a.run_id)}>Retry</Button>
                    <Button size="small" color="warning" disabled={busy} onClick={() => dismiss(a.run_id)}>Dismiss</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Section>
      )}

      <Section title="Send results" subtitle="Write each finished run into the table immediately"
        actions={status && <StatusChip label={status.ready ? "configured" : (status.problem ?? "not configured")}
          kind={status.ready ? "pass" : "fail"} />}>
        <FormControlLabel label={cfg.enabled ? "On" : "Off"}
          control={<Switch checked={cfg.enabled} disabled={busy} onChange={(e) => toggle(e.target.checked)}
            inputProps={{ "aria-label": "send results" }} />} />
        {!cfg.enabled && <Alert severity="info" sx={{ mt: 1 }}>Off — nothing is written. Settings below are kept.</Alert>}
      </Section>

      <Section title="Database server" subtitle="Okaya's MES server (SQL Server or MySQL)">
        <DbServerForm value={conn} onChange={(p) => patch({ connection: { ...conn, ...p } })}
          password={password} onPassword={(p) => { setPassword(p); setDirty(true); }} />
        <Stack direction="row" spacing={2} alignItems="center" sx={{ mt: 2 }}>
          <Button variant="outlined" startIcon={<WifiTethering />} disabled={busy || !connReady} onClick={runTest}>
            Test connection
          </Button>
          {test && <StatusChip label={test.ok ? "connected" : (test.detail ?? "failed")} kind={test.ok ? "pass" : "fail"} />}
        </Stack>
      </Section>

      <Section title="Target table" subtitle="The existing table with the Okaya columns (txr_testtable layout)">
        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
          <NameField label="Database" what="databases" value={cfg.database} list={dbs}
            onChange={(v) => patch({ database: v })} />
          <NameField label="Table" what="tables" value={cfg.table} list={tables}
            onChange={(v) => patch({ table: v })} />
          <TextField label="Station name" size="small" sx={{ width: 220 }} value={cfg.station_name}
            helperText="Value of the station_name column" inputProps={{ maxLength: 50 }}
            onChange={(e) => patch({ station_name: e.target.value })} />
        </Stack>
        <Stack direction="row" spacing={2} alignItems="center" sx={{ mt: 2 }}>
          <Button variant="outlined" disabled={busy || !connReady || !cfg.table} onClick={runCheck}>Check table</Button>
          <Button variant="outlined" color="warning" disabled={busy || !connReady || !cfg.table} onClick={runCreate}>
            Create table
          </Button>
          {check && <StatusChip label={check.ok ? "table fits" : (check.detail ?? "does not fit")} kind={check.ok ? "pass" : "fail"} />}
        </Stack>
        {check && !check.ok && (check.missing?.length ?? 0) > 0 && (
          <Alert severity="warning" sx={{ mt: 2 }}>
            Missing column(s): <span style={{ fontFamily: MONO_STACK }}>{check.missing.join(", ")}</span>
          </Alert>
        )}
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
          Create table only makes a NEW table (it never alters an existing one). All columns are varchar(50) except date_time.
        </Typography>
      </Section>

      <Box sx={{ mb: 3 }}>
        <Button variant="contained" startIcon={<Save />} disabled={busy || !dirty} onClick={save}>Save</Button>
      </Box>

      <Section title="Check one run" subtitle="Preview the exact row for a run, or send it now (also backfills runs made before this was switched on)">
        <Stack direction="row" spacing={2} alignItems="center">
          <TextField label="Run id" size="small" sx={{ width: 360 }} value={runId}
            onChange={(e) => setRunId(e.target.value)} inputProps={{ style: { fontFamily: MONO_STACK } }} />
          <Button variant="outlined" disabled={busy || !runId.trim()} onClick={doPreview}>Preview row</Button>
          <Button variant="outlined" color="warning" disabled={busy || !runId.trim() || !status?.ready} onClick={send}>
            Send now
          </Button>
        </Stack>
        {preview ? (
          <Table size="small" sx={{ mt: 2 }}>
            <TableBody>
              {preview.columns.map((c: string) => (
                <TableRow key={c}>
                  <TableCell sx={{ fontFamily: MONO_STACK, width: 360 }}>{c}</TableCell>
                  <TableCell sx={{ fontFamily: MONO_STACK }}>{preview.row[c] ?? <em>NULL</em>}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : <EmptyState message="Enter a run id to preview its row." />}
      </Section>
    </Box>
  );
}
