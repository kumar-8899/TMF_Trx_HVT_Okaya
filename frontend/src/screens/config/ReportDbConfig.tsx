/** Report database config (Settings). Reports are stored on a professional DB
 * (MySQL / SQL Server) — pick the provider, enter connection params, test, save.
 * super_admin only (SYSTEM.SETTINGS); the API redacts the stored password. */
import { Save, WifiTethering } from "@mui/icons-material";
import { Alert, Button, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { DbServerForm, type ServerConn } from "../../components/DbServerForm";
import { Section, StatusChip, type StatusKind } from "../../components/ui";

type DbConfig = ServerConn & { configured?: boolean };

const TEST_KIND: Record<string, StatusKind> = { pass: "pass", fail: "fail", error: "fail" };

export function ReportDbConfig() {
  const [cfg, setCfg] = useState<DbConfig>({});
  const [password, setPassword] = useState("");
  const [test, setTest] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    api.get("/reports/db-config").then(setCfg).catch((e) => setError(e.message));
  }, []);

  const patch = (p: Partial<ServerConn>) => { setCfg((c) => ({ ...c, ...p })); setTest(null); };
  const body = () => ({ ...cfg, ...(password ? { password } : {}) });

  const runTest = async () => {
    setBusy(true); setError(null); setTest(null);
    try { setTest(await api.post("/reports/db-config/test", body())); }
    catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };
  const save = async () => {
    setBusy(true); setError(null); setNotice(null);
    try {
      setCfg(await api.put("/reports/db-config", body()));
      setPassword("");
      setNotice("Saved. New reports are stored to this database; queued reports drain to it.");
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Section title="Report database"
      subtitle="Reports are stored on a professional DB (MySQL / SQL Server), not the local station">
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}
      <Stack spacing={2}>
        <DbServerForm value={cfg} onChange={patch} password={password}
          onPassword={(p) => { setPassword(p); setTest(null); }} showDatabase
          providerExtra={cfg.configured ? <StatusChip label="configured" kind="pass" /> : undefined} />

        {cfg.provider && (
          <>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Button variant="outlined" startIcon={<WifiTethering />} disabled={busy || !cfg.host} onClick={runTest}>
                Test connection
              </Button>
              <Button variant="contained" startIcon={<Save />} disabled={busy || !cfg.host} onClick={save}>Save</Button>
              {test && <StatusChip label={test.status} kind={TEST_KIND[test.status] ?? "idle"} />}
              {test && <Typography variant="body2" color="text.secondary">{test.detail}</Typography>}
            </Stack>
            <Typography variant="caption" color="text.secondary">
              Test creates the report tables if missing. SQL Server also needs the OS "ODBC Driver 18 for
              SQL Server". Reports are spooled locally and forwarded, so a DB outage never blocks testing.
            </Typography>
          </>
        )}
      </Stack>
    </Section>
  );
}
