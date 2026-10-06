/** MES outbound — one row per run into ONE table, using the report header schema (DUT metadata, no
 * per-test data). The target database/table can be existing or new; for an existing customer table the
 * report fields are mapped to its columns (auto-matched by name, remappable, optional ones skippable).
 * The result is sent the moment a run finishes; a failure is shown loudly (see MesAlertDialog). */
import { Save, WifiTethering } from "@mui/icons-material";
import {
  Alert, Box, Button, Checkbox, Chip, FormControlLabel, Stack, Step, StepButton, StepContent, Stepper,
  Switch, Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from "@mui/material";
import { useEffect, useRef, useState } from "react";

import { api } from "../../../api/client";
import { DbServerForm, type ServerConn } from "../../../components/DbServerForm";
import { Section, StatusChip } from "../../../components/ui";
import { MONO_STACK } from "../../../theme/theme";
import { connBody, NameField, useListing } from "./common";

export interface OutboundCfg {
  same_as_inbound?: boolean; connection?: ServerConn; database?: string; table?: string;
  column_map?: Record<string, string>;
}
export interface MesField { name: string; required: boolean; type: string }

interface Props {
  saved: OutboundCfg;
  inboundConnection?: ServerConn;
  fields: MesField[];
  enabled: boolean;
  onToggle: (v: boolean) => void;
  onSaved: (db: any) => void;
}

/** Match each field to a column of an existing table by name, case-insensitively ("" = no match). */
export function autoMap(fields: MesField[], columns: string[]): Record<string, string> {
  const lower = new Map(columns.map((c) => [c.toLowerCase(), c]));
  return Object.fromEntries(fields.map((f) => [f.name, lower.get(f.name.toLowerCase()) ?? ""]));
}

export function OutboundCard({ saved, inboundConnection, fields, enabled, onToggle, onSaved }: Props) {
  const [d, setD] = useState<OutboundCfg>({ ...saved });
  const [password, setPassword] = useState("");
  const [step, setStep] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [test, setTest] = useState<any | null>(null);
  const [check, setCheck] = useState<any | null>(null);
  const [addMissing, setAddMissing] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const same = Boolean(d.same_as_inbound);
  const conn = same ? (inboundConnection ?? {}) : (d.connection ?? {});
  const connReady = Boolean(conn.provider && conn.host);
  const connKey = [same, conn.provider, conn.host, conn.port, conn.user, conn.odbc_driver];
  const cb = same ? undefined : connBody(conn, password);
  const sideArgs = { side: "outbound", same_as_inbound: same, connection: cb };
  const patch = (p: Partial<OutboundCfg>) => { setD((x) => ({ ...x, ...p })); setDirty(true); setNotice(null); setCheck(null); };

  const dbs = useListing(connReady && step >= 1 ? () => api.post("/mes/db/databases", sideArgs) : null,
    [...connKey, step >= 1]);
  const tables = useListing(connReady && d.database && step >= 2
    ? () => api.post("/mes/db/tables", { ...sideArgs, database: d.database }) : null,
    [...connKey, d.database, step >= 2]);
  const tableExists = tables.loaded && tables.ok ? tables.items.includes(d.table ?? "") : null;
  const cols = useListing(connReady && d.table && tableExists && step >= 3
    ? () => api.post("/mes/db/columns", { ...sideArgs, database: d.database, table: d.table }) : null,
    [...connKey, d.database, d.table, Boolean(tableExists), step >= 3], (c: any) => c.name);
  const dbIsNew = dbs.loaded && dbs.ok && Boolean(d.database) && !dbs.items.includes(d.database ?? "");

  // Auto-match the mapping once per chosen existing table (don't clobber a saved or hand-edited map).
  const mappedFor = useRef<string | undefined>(saved.column_map && Object.keys(saved.column_map).length ? saved.table : undefined);
  useEffect(() => {
    if (cols.loaded && cols.ok && tableExists && mappedFor.current !== d.table) {
      mappedFor.current = d.table;
      setD((x) => ({ ...x, column_map: autoMap(fields, cols.items) }));
      setDirty(true);
    }
  }, [cols.loaded, cols.ok, cols.items, tableExists, d.table, fields]);
  useEffect(() => { if (tableExists === false) mappedFor.current = undefined; }, [tableExists, d.table]);

  const mapOf = (f: string) => (d.column_map ? (d.column_map[f] ?? "") : f);   // no map yet = same names
  const setMap = (f: string, col: string) => {
    const base = d.column_map ?? Object.fromEntries(fields.map((x) => [x.name, x.name]));
    patch({ column_map: { ...base, [f]: col } });
  };

  const body = () => ({ ...d, ...(same ? {} : { connection: connBody(conn, password) }),
    column_map: Object.fromEntries(fields.map((f) => [f.name, mapOf(f.name)]).filter(([, c]) => c)) });
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(null);
    try { await fn(); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const runTest = () => run(async () => { setTest(await api.post("/mes/db/test", sideArgs)); dbs.reload(); });
  const runCheck = () => run(async () => { setCheck(await api.post("/mes/db/outbound/validate", { outbound: body() })); });
  const runEnsure = () => run(async () => {
    const r = await api.post("/mes/db/outbound/ensure", { outbound: body(), add_missing: addMissing });
    setCheck(r); tables.reload(); cols.reload();
  });
  const save = () => run(async () => {
    onSaved(await api.put("/mes/db-config", { outbound: body() }));
    setD((x) => ({ ...x, connection: { ...x.connection, has_password: Boolean(password) || Boolean(x.connection?.has_password) } }));
    setPassword(""); setDirty(false); setNotice("Saved.");
  });

  const unmappedRequired = fields.filter((f) => f.required && !mapOf(f.name));
  const done = [connReady, Boolean(d.database), Boolean(d.table), Boolean(d.table) && unmappedRequired.length === 0, Boolean(check?.ok)];
  const labels = ["Server", "Database", "Table", "Columns", "Apply"];
  const nextBtn = <Button size="small" sx={{ mt: 1, alignSelf: "flex-start" }} onClick={() => setStep((s) => Math.min(4, s + 1))}>Next</Button>;

  return (
    <Section title="Outbound — publish"
      subtitle="Write each finished run into one table, immediately"
      actions={
        <FormControlLabel sx={{ m: 0, color: "inherit" }} label={enabled ? "On" : "Off"}
          control={<Switch size="small" checked={enabled} onChange={(e) => onToggle(e.target.checked)}
            inputProps={{ "aria-label": "outbound enabled" }} />} />
      }>
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}
      {!enabled && <Alert severity="info" sx={{ mb: 2 }}>Outbound is off — nothing is sent. Settings below are kept.</Alert>}
      <Box sx={{ opacity: enabled ? 1 : 0.65 }}>
        <Stepper nonLinear activeStep={step} orientation="vertical">
          {labels.map((label, i) => (
            <Step key={label} completed={done[i]}>
              <StepButton onClick={() => setStep(i)}>{label}</StepButton>
              <StepContent TransitionProps={{ unmountOnExit: true }}>
                {i === 0 && (
                  <Stack spacing={2}>
                    <FormControlLabel label="Use the same server as inbound"
                      control={<Checkbox size="small" checked={same} disabled={!inboundConnection?.host}
                        onChange={(e) => { patch({ same_as_inbound: e.target.checked }); setTest(null); }} />} />
                    {same
                      ? <Typography variant="body2" color="text.secondary">
                          {inboundConnection?.host ? `${inboundConnection.provider} · ${inboundConnection.host}` : "Save the inbound server first."}
                        </Typography>
                      : <DbServerForm value={conn} onChange={(p) => { patch({ connection: { ...conn, ...p } }); setTest(null); }}
                          password={password} onPassword={(p) => { setPassword(p); setTest(null); setDirty(true); }} />}
                    {connReady && (
                      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                        <Button variant="outlined" startIcon={<WifiTethering />} disabled={busy} onClick={runTest}>Test connection</Button>
                        {test && <StatusChip label={test.status} kind={test.ok ? "pass" : "fail"} />}
                        {test && <Typography variant="body2" color="text.secondary">{test.detail}</Typography>}
                      </Stack>
                    )}
                    {nextBtn}
                  </Stack>
                )}
                {i === 1 && (
                  <Stack spacing={1.5}>
                    <Stack direction="row" spacing={1} alignItems="flex-start">
                      <NameField label="Database" what="databases" value={d.database ?? ""} list={dbs}
                        hint="Pick one, or type a new name — it is created when you apply (needs CREATE rights)."
                        onChange={(v) => patch({ database: v })} width={320} />
                      {dbIsNew && <Chip size="small" color="info" label="new — will be created" sx={{ mt: 1 }} />}
                    </Stack>
                    {nextBtn}
                  </Stack>
                )}
                {i === 2 && (
                  <Stack spacing={1.5}>
                    <Stack direction="row" spacing={1} alignItems="flex-start">
                      <NameField label="Table" what="tables" value={d.table ?? ""} list={tables} width={320}
                        hint="Pick an existing table, or type a new name to create it. schema.table is allowed."
                        onChange={(v) => patch({ table: v })} />
                      {tableExists === true && <Chip size="small" label="existing table" sx={{ mt: 1 }} />}
                      {tableExists === false && Boolean(d.table) && <Chip size="small" color="info" label="new — will be created" sx={{ mt: 1 }} />}
                    </Stack>
                    {nextBtn}
                  </Stack>
                )}
                {i === 3 && (
                  <Stack spacing={1.5}>
                    <Typography variant="body2" color="text.secondary">
                      {tableExists === false
                        ? "The table will be created with these columns (the report header schema — no per-test data). You can rename them."
                        : "Match each field to a column of the table. Empty = not written (optional fields only)."}
                    </Typography>
                    <Table size="small">
                      <TableHead><TableRow>
                        <TableCell>Field</TableCell><TableCell>Type (new table)</TableCell><TableCell>Column</TableCell>
                      </TableRow></TableHead>
                      <TableBody>
                        {fields.map((f) => (
                          <TableRow key={f.name}>
                            <TableCell sx={{ fontFamily: MONO_STACK }}>{f.name}{f.required ? " *" : ""}</TableCell>
                            <TableCell sx={{ color: "text.secondary" }}>{f.type}</TableCell>
                            <TableCell>
                              <NameField label={f.required ? "required" : "optional"} what="columns" value={mapOf(f.name)}
                                list={cols} width={240} onChange={(v) => setMap(f.name, v)} />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    {unmappedRequired.length > 0 && (
                      <Alert severity="warning">Map the required field(s): {unmappedRequired.map((f) => f.name).join(", ")}. run_id keys the one-row-per-run update.</Alert>
                    )}
                    {nextBtn}
                  </Stack>
                )}
                {i === 4 && (
                  <Stack spacing={1.5}>
                    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                      <Button variant="outlined" disabled={busy || !d.table} onClick={runCheck}>Check table</Button>
                      <Button variant="contained" disabled={busy || !d.table || unmappedRequired.length > 0} onClick={runEnsure}>
                        {tableExists === false ? "Create table" : "Apply"}
                      </Button>
                      {tableExists !== false && (
                        <FormControlLabel label="Add missing columns"
                          control={<Checkbox size="small" checked={addMissing} onChange={(e) => setAddMissing(e.target.checked)} />} />
                      )}
                    </Stack>
                    {check && (
                      <Stack spacing={0.5}>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <StatusChip label={check.ok ? "table fits" : "needs attention"} kind={check.ok ? "pass" : "fail"} />
                          <Typography variant="body2">{check.detail}</Typography>
                        </Stack>
                        {check.blocking?.length > 0 && (
                          <Typography variant="caption" color="error">
                            Writes would fail: NOT NULL column(s) without a default that are not mapped — map them or give them a default in the database.
                          </Typography>
                        )}
                      </Stack>
                    )}
                    <Typography variant="caption" color="text.secondary">
                      Creating a database or table, or adding columns, only happens here — never while testing.
                    </Typography>
                  </Stack>
                )}
              </StepContent>
            </Step>
          ))}
        </Stepper>
      </Box>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 2 }}>
        <Button variant="contained" startIcon={<Save />} disabled={busy || !dirty} onClick={save}>Save outbound</Button>
        {dirty && <StatusChip label="unsaved changes" kind="idle" />}
        {notice && <Typography variant="body2" color="success.main">{notice}</Typography>}
      </Stack>
    </Section>
  );
}
