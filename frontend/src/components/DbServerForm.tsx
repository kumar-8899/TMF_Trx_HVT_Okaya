/** Database SERVER connection fields (provider, host, port, [database], user, password, ODBC driver).
 * Shared by Settings → Report database and Config → MES so the form, the port defaults and the
 * password convention ("•••••• (unchanged)", blank = keep) live in one place. The parent owns the
 * state, the Test/Save buttons and the API calls. */
import { MenuItem, Stack, TextField } from "@mui/material";
import type { ReactNode } from "react";

export interface ServerConn {
  provider?: string; host?: string; port?: number | string; database?: string;
  user?: string; odbc_driver?: string; has_password?: boolean;
}

export const PORTS: Record<string, number> = { mysql: 3306, sqlserver: 1433 };

interface Props {
  value: ServerConn;
  onChange: (patch: Partial<ServerConn>) => void;
  /** The typed password (never the stored one — the API never returns it). */
  password: string;
  onPassword: (p: string) => void;
  /** Report DB names its database in this form; MES picks it from a list in a later step. */
  showDatabase?: boolean;
  /** Rendered right of the provider select (e.g. a "configured" chip). */
  providerExtra?: ReactNode;
  disabled?: boolean;
}

export function DbServerForm({ value, onChange, password, onPassword, showDatabase = false,
                               providerExtra, disabled }: Props) {
  const isSql = value.provider === "sqlserver";
  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="center">
        <TextField select label="Provider" value={value.provider ?? ""} sx={{ width: 180 }} disabled={disabled}
          onChange={(e) => {
            const p = e.target.value;
            onChange({ provider: p, ...(!value.port && PORTS[p] ? { port: PORTS[p] } : {}) });
          }}
          inputProps={{ "aria-label": "provider" }}>
          <MenuItem value=""><em>select…</em></MenuItem>
          <MenuItem value="mysql">MySQL</MenuItem>
          <MenuItem value="sqlserver">SQL Server</MenuItem>
        </TextField>
        {providerExtra}
      </Stack>

      {value.provider && (
        <>
          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
            <TextField label="Host" value={value.host ?? ""} sx={{ width: 220 }} disabled={disabled}
              onChange={(e) => onChange({ host: e.target.value })} />
            <TextField label="Port" type="number" value={value.port ?? PORTS[value.provider] ?? ""} sx={{ width: 110 }}
              disabled={disabled}
              onChange={(e) => onChange({ port: e.target.value === "" ? "" : Number(e.target.value) })} />
            {showDatabase && (
              <TextField label="Database" value={value.database ?? ""} sx={{ width: 200 }} disabled={disabled}
                onChange={(e) => onChange({ database: e.target.value })} />
            )}
          </Stack>
          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
            <TextField label="User" value={value.user ?? ""} sx={{ width: 200 }} disabled={disabled}
              onChange={(e) => onChange({ user: e.target.value })} />
            <TextField label="Password" type="password" value={password} sx={{ width: 200 }} disabled={disabled}
              placeholder={value.has_password ? "•••••• (unchanged)" : ""}
              onChange={(e) => onPassword(e.target.value)} />
            {isSql && (
              <TextField label="ODBC driver" value={value.odbc_driver ?? ""} sx={{ width: 260 }} disabled={disabled}
                placeholder="ODBC Driver 18 for SQL Server" onChange={(e) => onChange({ odbc_driver: e.target.value })} />
            )}
          </Stack>
        </>
      )}
    </Stack>
  );
}
