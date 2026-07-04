/** Report database config (Settings). Reports are stored on a professional DB
 * (MySQL / SQL Server) — pick the provider, enter connection params, test, save.
 * super_admin only (SYSTEM.SETTINGS); the API redacts the stored password. */
import { Save, WifiTethering } from "@mui/icons-material";
import {
  Alert, Button, MenuItem, Stack, TextField, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { Section, StatusChip, type StatusKind } from "../../components/ui";

interface DbConfig {
  provider?: string; host?: string; port?: number | string; database?: string;
  user?: string; odbc_driver?: string; has_password?: boolean; configured?: boolean;
}

const TEST_KIND: Record<string, StatusKind> = { pass: "pass", fail: "fail", error: "fail" };
const PORTS: Record<string, number> = { mysql: 3306, sqlserver: 1433 };

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

  const set = (k: keyof DbConfig, v: any) => { setCfg((c) => ({ ...c, [k]: v })); setTest(null); };
  const isSql = cfg.provider === "sqlserver";
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
        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="center">
          <TextField select label="Provider" value={cfg.provider ?? ""} sx={{ width: 180 }}
            onChange={(e) => { set("provider", e.target.value); if (!cfg.port) set("port", PORTS[e.target.value]); }}
            inputProps={{ "aria-label": "provider" }}>
            <MenuItem value=""><em>select…</em></MenuItem>
            <MenuItem value="mysql">MySQL</MenuItem>
            <MenuItem value="sqlserver">SQL Server</MenuItem>
          </TextField>
          {cfg.configured && <StatusChip label="configured" kind="pass" />}
        </Stack>

        {cfg.provider && (
          <>
            <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
              <TextField label="Host" value={cfg.host ?? ""} sx={{ width: 220 }} onChange={(e) => set("host", e.target.value)} />
              <TextField label="Port" type="number" value={cfg.port ?? PORTS[cfg.provider] ?? ""} sx={{ width: 110 }}
                onChange={(e) => set("port", e.target.value === "" ? "" : Number(e.target.value))} />
              <TextField label="Database" value={cfg.database ?? ""} sx={{ width: 200 }} onChange={(e) => set("database", e.target.value)} />
            </Stack>
            <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
              <TextField label="User" value={cfg.user ?? ""} sx={{ width: 200 }} onChange={(e) => set("user", e.target.value)} />
              <TextField label="Password" type="password" value={password} sx={{ width: 200 }}
                placeholder={cfg.has_password ? "•••••• (unchanged)" : ""}
                onChange={(e) => { setPassword(e.target.value); setTest(null); }} />
              {isSql && (
                <TextField label="ODBC driver" value={cfg.odbc_driver ?? ""} sx={{ width: 260 }}
                  placeholder="ODBC Driver 18 for SQL Server" onChange={(e) => set("odbc_driver", e.target.value)} />
              )}
            </Stack>
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
