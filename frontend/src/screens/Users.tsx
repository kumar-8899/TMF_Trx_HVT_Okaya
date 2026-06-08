import {
  Alert, Button, Chip, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow,
  TextField, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../api/client";

interface User {
  username: string;
  role: string;
  state: string;
}

const STATE_COLOR: Record<string, "success" | "warning" | "error" | "default"> = {
  ACTIVE: "success",
  PASSWORD_RESET_REQUIRED: "warning",
  LOCKED: "error",
  INACTIVE: "default",
};

export function Users() {
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // new-user form
  const [nu, setNu] = useState({ username: "", password: "", role: "operator" });

  const refresh = () =>
    api.get("/auth/users").then((list: User[]) => {
      setUsers(list);
      setRoles(Object.fromEntries(list.map((u) => [u.username, u.role])));
    }).catch((e) => setError(e.message));

  useEffect(() => { refresh(); }, []);

  const act = async (fn: () => Promise<unknown>, ok?: string) => {
    setError(null); setNotice(null);
    try { await fn(); if (ok) setNotice(ok); await refresh(); }
    catch (e: any) { setError(e.message); }
  };

  const create = () => act(async () => {
    await api.post("/auth/users", nu);
    setNu({ username: "", password: "", role: "operator" });
  }, "user created");

  const reset = (name: string) => act(async () => {
    const r = await api.post(`/auth/users/${name}/reset-password`, {});
    setNotice(`temp password for ${name}: ${r.temp_password}`);
  });

  return (
    <Stack spacing={2}>
      <Typography variant="h5">Users</Typography>
      {error && <Alert severity="error">{error}</Alert>}
      {notice && <Alert severity="info">{notice}</Alert>}

      <Paper sx={{ p: 2 }}>
        <Typography variant="h6">New user</Typography>
        <Stack direction="row" spacing={1} sx={{ mt: 1 }} alignItems="center">
          <TextField size="small" label="username" value={nu.username}
            onChange={(e) => setNu({ ...nu, username: e.target.value })} />
          <TextField size="small" label="password" type="password" value={nu.password}
            onChange={(e) => setNu({ ...nu, password: e.target.value })} />
          <TextField size="small" label="role" value={nu.role}
            onChange={(e) => setNu({ ...nu, role: e.target.value })} />
          <Button variant="contained" onClick={create}
            disabled={!nu.username || !nu.password}>Create</Button>
        </Stack>
      </Paper>

      <Paper>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Username</TableCell><TableCell>Role</TableCell>
              <TableCell>State</TableCell><TableCell>Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {users.map((u) => (
              <TableRow key={u.username}>
                <TableCell>{u.username}</TableCell>
                <TableCell>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <TextField size="small" variant="standard" value={roles[u.username] ?? ""}
                      onChange={(e) => setRoles({ ...roles, [u.username]: e.target.value })}
                      inputProps={{ "aria-label": `role-${u.username}` }} />
                    <Button size="small" onClick={() =>
                      act(() => api.put(`/auth/users/${u.username}/role`, { role: roles[u.username] }), "role updated")}>
                      Set
                    </Button>
                  </Stack>
                </TableCell>
                <TableCell><Chip size="small" label={u.state} color={STATE_COLOR[u.state] ?? "default"} /></TableCell>
                <TableCell>
                  <Stack direction="row" spacing={1}>
                    {u.state === "LOCKED"
                      ? <Button size="small" onClick={() => act(() => api.post(`/auth/users/${u.username}/unlock`), "unlocked")}>Unlock</Button>
                      : <Button size="small" onClick={() => act(() => api.post(`/auth/users/${u.username}/lock`), "locked")}>Lock</Button>}
                    {u.state === "INACTIVE"
                      ? <Button size="small" onClick={() => act(() => api.post(`/auth/users/${u.username}/activate`), "activated")}>Activate</Button>
                      : <Button size="small" onClick={() => act(() => api.post(`/auth/users/${u.username}/deactivate`), "deactivated")}>Deactivate</Button>}
                    <Button size="small" onClick={() => reset(u.username)}>Reset pw</Button>
                  </Stack>
                </TableCell>
              </TableRow>
            ))}
            {users.length === 0 && <TableRow><TableCell colSpan={4}>No users.</TableCell></TableRow>}
          </TableBody>
        </Table>
      </Paper>
    </Stack>
  );
}
