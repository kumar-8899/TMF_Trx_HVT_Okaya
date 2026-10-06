/** MES inbound — the gate. A guided process against the customer's MES database (read-only):
 * server → database → table → columns (serial, status, allow value) → latest-by → try a serial.
 * Equal to the allow value = allowed; anything else = blocked. */
import { ArrowDownward, ArrowUpward, Delete, Save, WifiTethering } from "@mui/icons-material";
import {
  Alert, Box, Button, Checkbox, FormControlLabel, IconButton, Stack, Step, StepButton, StepContent,
  Stepper, Switch, TextField, Typography,
} from "@mui/material";
import { useState } from "react";

import { api } from "../../../api/client";
import { DbServerForm, type ServerConn } from "../../../components/DbServerForm";
import { Section, StatusChip } from "../../../components/ui";
import { connBody, NameField, useListing } from "./common";

export interface InboundCfg {
  connection?: ServerConn; database?: string; table?: string; serial_column?: string;
  status_column?: string; allow_value?: string; ignore_case?: boolean; latest_by?: string[];
}

const MAX_LATEST = 4;

interface Props {
  saved: InboundCfg;
  enabled: boolean;
  onToggle: (v: boolean) => void;
  onSaved: (db: any) => void;
}

export function InboundCard({ saved, enabled, onToggle, onSaved }: Props) {
  const [d, setD] = useState<InboundCfg>({ ignore_case: true, ...saved, latest_by: saved.latest_by ?? [] });
  const [password, setPassword] = useState("");
  const [step, setStep] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [test, setTest] = useState<any | null>(null);
  const [verify, setVerify] = useState<any | null>(null);
  const [serial, setSerial] = useState("");
  const [tried, setTried] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const conn = d.connection ?? {};
  const connReady = Boolean(conn.provider && conn.host);
  const connKey = [conn.provider, conn.host, conn.port, conn.user, conn.odbc_driver];
  const cb = connBody(conn, password);
  const patch = (p: Partial<InboundCfg>) => { setD((x) => ({ ...x, ...p })); setDirty(true); setNotice(null); };
  const patchConn = (p: Partial<ServerConn>) => { patch({ connection: { ...conn, ...p } }); setTest(null); };

  const dbs = useListing(connReady && step >= 1 ? () => api.post("/mes/db/databases", { side: "inbound", connection: cb }) : null,
    [...connKey, step >= 1]);
  const tables = useListing(connReady && d.database && step >= 2
    ? () => api.post("/mes/db/tables", { side: "inbound", connection: cb, database: d.database }) : null,
    [...connKey, d.database, step >= 2]);
  const cols = useListing(connReady && d.table && step >= 3
    ? () => api.post("/mes/db/columns", { side: "inbound", connection: cb, database: d.database, table: d.table }) : null,
    [...connKey, d.database, d.table, step >= 3], (c: any) => c.name);
  const values = useListing(connReady && d.table && d.status_column && step >= 3
    ? () => api.post("/mes/db/values", { connection: cb, database: d.database, table: d.table, column: d.status_column }) : null,
    [...connKey, d.database, d.table, d.status_column, step >= 3]);

  const body = () => ({ ...d, connection: cb });
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(null);
    try { await fn(); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };

  const runTest = () => run(async () => {
    setTest(await api.post("/mes/db/test", { side: "inbound", connection: cb }));
    dbs.reload();
  });
  const runVerify = () => run(async () => {
    setVerify(await api.post("/mes/db/verify", {
      side: "inbound", connection: cb, database: d.database, table: d.table,
      columns: [d.serial_column, d.status_column, ...(d.latest_by ?? [])],
    }));
  });
  const runTry = () => run(async () => { setTried(await api.post("/mes/db/inbound/check", { serial, inbound: body() })); });
  const save = () => run(async () => {
    onSaved(await api.put("/mes/db-config", { inbound: body() }));
    setD((x) => ({ ...x, connection: { ...x.connection, has_password: Boolean(password) || Boolean(x.connection?.has_password) } }));
    setPassword(""); setDirty(false); setNotice("Saved.");
  });

  const latest = d.latest_by ?? [];
  const setLatest = (next: string[]) => patch({ latest_by: next });
  const move = (i: number, dir: -1 | 1) => {
    const n = [...latest]; const j = i + dir;
    if (j < 0 || j >= n.length) return;
    [n[i], n[j]] = [n[j], n[i]]; setLatest(n);
  };

  const done = [
    connReady,
    Boolean(d.database),
    Boolean(d.table),
    Boolean(d.serial_column && d.status_column && (d.allow_value ?? "") !== ""),
    latest.length > 0,
    Boolean(tried),
  ];
  const labels = ["Server", "Database", "Table", "Columns", "Latest by", "Try a serial"];
  const nextBtn = (
    <Button size="small" sx={{ mt: 1, alignSelf: "flex-start" }} onClick={() => setStep((s) => Math.min(5, s + 1))}>Next</Button>
  );

  return (
    <Section title="Inbound — gate"
      subtitle="Look the unit up in the MES database before a run starts"
      actions={
        <FormControlLabel sx={{ m: 0, color: "inherit" }} label={enabled ? "On" : "Off"}
          control={<Switch size="small" checked={enabled} onChange={(e) => onToggle(e.target.checked)}
            inputProps={{ "aria-label": "inbound enabled" }} />} />
      }>
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}
      {!enabled && (
        <Alert severity="info" sx={{ mb: 2 }}>Inbound is off — runs are not checked. Settings below are kept.</Alert>
      )}
      <Box sx={{ opacity: enabled ? 1 : 0.65 }}>
        <Stepper nonLinear activeStep={step} orientation="vertical">
          {labels.map((label, i) => (
            <Step key={label} completed={done[i]}>
              <StepButton onClick={() => setStep(i)}>{label}</StepButton>
              <StepContent TransitionProps={{ unmountOnExit: true }}>
                {i === 0 && (
                  <Stack spacing={2}>
                    <DbServerForm value={conn} onChange={patchConn} password={password}
                      onPassword={(p) => { setPassword(p); setTest(null); setDirty(true); }} />
                    {conn.provider && (
                      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                        <Button variant="outlined" startIcon={<WifiTethering />} disabled={busy || !connReady} onClick={runTest}>
                          Test connection
                        </Button>
                        {test && <StatusChip label={test.status} kind={test.ok ? "pass" : "fail"} />}
                        {test && <Typography variant="body2" color="text.secondary">{test.detail}</Typography>}
                      </Stack>
                    )}
                    <Typography variant="caption" color="text.secondary">
                      The gate only reads this database — it never writes or creates anything here.
                    </Typography>
                    {nextBtn}
                  </Stack>
                )}
                {i === 1 && (
                  <Stack spacing={1.5}>
                    <NameField label="Database" what="databases" value={d.database ?? ""} list={dbs}
                      onChange={(v) => patch({ database: v })} />
                    {nextBtn}
                  </Stack>
                )}
                {i === 2 && (
                  <Stack spacing={1.5}>
                    <NameField label="Table or view" what="tables" value={d.table ?? ""} list={tables} width={320}
                      hint="Use schema.table for a table outside the default schema."
                      onChange={(v) => patch({ table: v })} />
                    {nextBtn}
                  </Stack>
                )}
                {i === 3 && (
                  <Stack spacing={2}>
                    <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                      <NameField label="Serial number column" what="columns" value={d.serial_column ?? ""} list={cols}
                        hint="Where the unit's serial / barcode is stored." onChange={(v) => patch({ serial_column: v })} />
                      <NameField label="Status column" what="columns" value={d.status_column ?? ""} list={cols}
                        hint="Where the previous stage's result is stored." onChange={(v) => patch({ status_column: v })} />
                    </Stack>
                    <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="flex-start">
                      <NameField label="Allow value" what="values" value={d.allow_value ?? ""} list={values} width={220}
                        hint="Equal = allowed. Anything else = blocked."
                        onChange={(v) => patch({ allow_value: v })} />
                      <FormControlLabel label="Ignore upper/lower case"
                        control={<Checkbox size="small" checked={d.ignore_case !== false}
                          onChange={(e) => patch({ ignore_case: e.target.checked })} />} />
                    </Stack>
                    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                      <Button variant="outlined" size="small" disabled={busy || !d.table} onClick={runVerify}>
                        Verify names
                      </Button>
                      {verify && <StatusChip label={verify.ok ? "found" : "not found"} kind={verify.ok ? "pass" : "fail"} />}
                      {verify && <Typography variant="body2" color="text.secondary">{verify.detail}</Typography>}
                    </Stack>
                    {nextBtn}
                  </Stack>
                )}
                {i === 4 && (
                  <Stack spacing={1.5}>
                    <Typography variant="body2" color="text.secondary">
                      If the table keeps several rows per unit, the <b>newest</b> row decides. Add the date column, then
                      the time column when they are stored separately. Leave empty if a unit has one row —
                      with several rows and no column here, <i>every</i> row must equal the allow value.
                    </Typography>
                    {latest.map((c, idx) => (
                      <Stack key={idx} direction="row" spacing={1} alignItems="flex-start">
                        <Typography variant="body2" sx={{ width: 90, pt: 1 }}>
                          {idx === 0 ? "Newest by" : "then by"}
                        </Typography>
                        <NameField label={`Column ${idx + 1}`} what="columns" value={c} list={cols}
                          onChange={(v) => setLatest(latest.map((x, k) => (k === idx ? v : x)))} />
                        <IconButton size="small" aria-label="move up" disabled={idx === 0} onClick={() => move(idx, -1)}><ArrowUpward fontSize="small" /></IconButton>
                        <IconButton size="small" aria-label="move down" disabled={idx === latest.length - 1} onClick={() => move(idx, 1)}><ArrowDownward fontSize="small" /></IconButton>
                        <IconButton size="small" aria-label="remove column" onClick={() => setLatest(latest.filter((_, k) => k !== idx))}><Delete fontSize="small" /></IconButton>
                      </Stack>
                    ))}
                    <Box>
                      <Button size="small" variant="outlined" disabled={latest.length >= MAX_LATEST}
                        onClick={() => setLatest([...latest, ""])}>
                        Add column
                      </Button>
                    </Box>
                    <Typography variant="caption" color="text.secondary">
                      Sorted the way the database sorts the column's type — real date/time types or yyyy-mm-dd
                      text work; text such as dd/mm/yyyy would sort wrongly.
                    </Typography>
                    {nextBtn}
                  </Stack>
                )}
                {i === 5 && (
                  <Stack spacing={1.5}>
                    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                      <TextField size="small" label="Serial number" value={serial} onChange={(e) => setSerial(e.target.value)} />
                      <Button variant="outlined" disabled={busy || !serial.trim()} onClick={runTry}>Try</Button>
                    </Stack>
                    {tried && (
                      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                        <StatusChip label={tried.allowed ? "ALLOWED" : "BLOCKED"} kind={tried.allowed ? "pass" : "fail"} />
                        <Typography variant="body2">{tried.detail}</Typography>
                        {tried.matched > 0 && (
                          <Typography variant="caption" color="text.secondary">
                            {tried.matched} row(s) found{tried.rows?.length ? `: ${tried.rows.join(", ")}` : ""}
                          </Typography>
                        )}
                      </Stack>
                    )}
                  </Stack>
                )}
              </StepContent>
            </Step>
          ))}
        </Stepper>
      </Box>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 2 }}>
        <Button variant="contained" startIcon={<Save />} disabled={busy || !dirty} onClick={save}>Save inbound</Button>
        {dirty && <StatusChip label="unsaved changes" kind="idle" />}
        {notice && <Typography variant="body2" color="success.main">{notice}</Typography>}
      </Stack>
    </Section>
  );
}
