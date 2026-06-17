import { Add, LockReset, PersonAdd } from "@mui/icons-material";
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Table,
  TableBody, TableCell, TableHead, TableRow, TextField, Tooltip,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { EmptyState, PageHeader, Section, StatusChip, statusKind } from "../components/ui";
import { MONO_STACK } from "../theme/theme";

interface User {
  username: string;
  role: string;
  state: string;
}

const PROTECTED = "super_admin";

export function Users() {
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
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
    setCreateOpen(false);
  }, "user created");

  const reset = (name: string) => act(async () => {
    const r = await api.post(`/auth/users/${name}/reset-password`, {});
    setNotice(`temp password for ${name}: ${r.temp_password}`);
  });

  return (
    <div>
      <PageHeader
        title="Users"
        subtitle="Accounts, roles, and access state"
        actions={
          <Button variant="contained" startIcon={<PersonAdd />} onClick={() => setCreateOpen(true)}>
            New user
          </Button>
        }
      />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {notice && <Alert severity="info" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}

      <Section sx={{ p: 0 }}>
        {users.length === 0 ? (
          <EmptyState message="No users." />
        ) : (
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Username</TableCell><TableCell>Role</TableCell>
                <TableCell>State</TableCell><TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {users.map((u) => {
                const protectedUser = u.role === PROTECTED;
                return (
                  <TableRow key={u.username}>
                    <TableCell sx={{ fontFamily: MONO_STACK, fontWeight: 600 }}>{u.username}</TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={1} alignItems="center">
                        <TextField variant="standard" value={roles[u.username] ?? ""} disabled={protectedUser}
                          onChange={(e) => setRoles({ ...roles, [u.username]: e.target.value })}
                          inputProps={{ "aria-label": `role-${u.username}` }} sx={{ width: 120 }} />
                        <Button size="small" disabled={protectedUser} onClick={() =>
                          act(() => api.put(`/auth/users/${u.username}/role`, { role: roles[u.username] }), "role updated")}>
                          Set
                        </Button>
                      </Stack>
                    </TableCell>
                    <TableCell><StatusChip label={u.state} kind={statusKind(u.state)} /></TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={1} justifyContent="flex-end">
                        {/* super_admin is protected: only its password may change */}
                        {u.state === "LOCKED"
                          ? <Button size="small" disabled={protectedUser} onClick={() => act(() => api.post(`/auth/users/${u.username}/unlock`), "unlocked")}>Unlock</Button>
                          : <Button size="small" color="warning" disabled={protectedUser} onClick={() => act(() => api.post(`/auth/users/${u.username}/lock`), "locked")}>Lock</Button>}
                        {u.state === "INACTIVE"
                          ? <Button size="small" disabled={protectedUser} onClick={() => act(() => api.post(`/auth/users/${u.username}/activate`), "activated")}>Activate</Button>
                          : <Button size="small" color="inherit" disabled={protectedUser} onClick={() => act(() => api.post(`/auth/users/${u.username}/deactivate`), "deactivated")}>Deactivate</Button>}
                        <Tooltip title="Reset password">
                          <Button size="small" startIcon={<LockReset />} onClick={() => reset(u.username)}>Reset pw</Button>
                        </Tooltip>
                      </Stack>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Section>

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>New user</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 0.5 }}>
            <TextField label="username" value={nu.username} autoFocus
              onChange={(e) => setNu({ ...nu, username: e.target.value })} />
            <TextField label="password" type="password" value={nu.password}
              onChange={(e) => setNu({ ...nu, password: e.target.value })} />
            <TextField label="role" value={nu.role}
              onChange={(e) => setNu({ ...nu, role: e.target.value })}
              helperText="Cannot create a second super_admin (singleton)." />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" startIcon={<Add />} disabled={!nu.username || !nu.password} onClick={create}>
            Create
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
}
