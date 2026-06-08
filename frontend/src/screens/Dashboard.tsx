import {
  Chip, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../api/client";

interface ModuleRow {
  id: string;
  status: string;
  reason: string;
  display_name: string;
}

export function Dashboard() {
  const [modules, setModules] = useState<ModuleRow[]>([]);
  const [ready, setReady] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get("/modules/status").then((s) => setModules(s.modules || [])).catch((e) => setError(e.message));
    api.get("/readyz").then(() => setReady(true)).catch(() => setReady(false));
  }, []);

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} alignItems="center">
        <Typography variant="h5">Station</Typography>
        <Chip
          label={ready === null ? "checking…" : ready ? "ready" : "not ready"}
          color={ready ? "success" : ready === false ? "warning" : "default"}
        />
      </Stack>
      {error && <Typography color="error">{error}</Typography>}
      <Paper>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Module</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Reason</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {modules.map((m) => (
              <TableRow key={m.id}>
                <TableCell>{m.display_name || m.id}</TableCell>
                <TableCell>
                  <Chip size="small" label={m.status}
                    color={m.status === "loaded" ? "success" : "default"} />
                </TableCell>
                <TableCell>{m.reason}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
    </Stack>
  );
}
