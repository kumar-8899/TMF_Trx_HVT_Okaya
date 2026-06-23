import { Add, LockPerson, LockReset, PersonAdd } from "@mui/icons-material";
import {
  Alert, Avatar, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem,
  Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Tooltip, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageHeader, Section, StatusChip, statusKind } from "../components/ui";
import { MONO_STACK } from "../theme/theme";

interface User {
  username: string;
  role: string;
  state: string;
}

const PROTECTED = "super_admin";

export function Users() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [roleOptions, setRoleOptions] = useState<string[]>([]);
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [nu, setNu] = useState({ username: "", role: "" });

  const refresh = () =>
    api.get("/auth/users").then((list: User[]) => {
      setUsers(list);
      setRoles(Object.fromEntries(list.map((u) => [u.username, u.role])));
    }).catch((e) => setError(e.message));

  useEffect(() => {
    refresh();
    // Roles the current viewer may assign (super_admin excluded; elevated roles
    // only for super_admin) — see docs/contracts/auth.md.
    api.get("/auth/roles").then((rs: string[]) => {
      setRoleOptions(rs);
      setNu((n) => ({ ...n, role: n.role || rs[0] || "" }));
    }).catch(() => setRoleOptions([]));
  }, []);

  const act = async (fn: () => Promise<unknown>, ok?: string) => {
    setError(null); setNotice(null);
    try { await fn(); if (ok) setNotice(ok); await refresh(); }
    catch (e: any) { setError(e.message); }
  };

  const create = () => act(async () => {
    const r = await api.post("/auth/users", { username: nu.username, role: nu.role });
    setNotice(`User "${nu.username}" created. Temporary password: ${r.temp_password} — they must change it on first login.`);
    setNu({ username: "", role: roleOptions[0] || "" });
    setCreateOpen(false);
  });

  const reset = (name: string) => act(async () => {
    const r = await api.post(`/auth/users/${name}/reset-password`, {});
    setNotice(`Temporary password for ${name}: ${r.temp_password} — they must change it on next login.`);
  });

  return (
    <div>
      <PageHeader
        title="Users"
        subtitle="Accounts, roles, and access state"
        actions={
          <Stack direction="row" spacing={1}>
            {can("AUTH.MANAGE_ROLES") && (
              <Button variant="outlined" startIcon={<LockPerson />} onClick={() => navigate("/permissions")}>
                Permissions
              </Button>
            )}
            <Button variant="contained" startIcon={<PersonAdd />} onClick={() => setCreateOpen(true)}>
              New user
            </Button>
          </Stack>
        }
      />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {notice && <Alert severity="info" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}

      <Section bodyPad={0}>
        {users.length === 0 ? (
          <EmptyState message="No users." />
        ) : (
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>User</TableCell><TableCell>Role</TableCell>
                <TableCell>State</TableCell><TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {users.map((u) => {
                const protectedUser = u.role === PROTECTED;
                // Show the user's current role even if it's outside the assignable set.
                const options = Array.from(new Set([roles[u.username] ?? u.role, ...roleOptions]));
                return (
                  <TableRow key={u.username}>
                    <TableCell>
                      <Stack direction="row" spacing={1.5} alignItems="center">
                        <Avatar sx={{ width: 30, height: 30, fontSize: 13, bgcolor: "primary.dark", color: "primary.contrastText" }}>
                          {u.username.slice(0, 2).toUpperCase()}
                        </Avatar>
                        <Typography sx={{ fontFamily: MONO_STACK, fontWeight: 600 }}>{u.username}</Typography>
                      </Stack>
                    </TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={1} alignItems="center">
                        <TextField select variant="standard" value={roles[u.username] ?? u.role} disabled={protectedUser}
                          onChange={(e) => setRoles({ ...roles, [u.username]: e.target.value })}
                          inputProps={{ "aria-label": `role-${u.username}` }} sx={{ minWidth: 130 }}>
                          {options.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
                        </TextField>
                        <Button size="small" disabled={protectedUser || (roles[u.username] ?? u.role) === u.role} onClick={() =>
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
                        <Tooltip title="Generate a new temporary password">
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
            <TextField select label="role" value={nu.role}
              onChange={(e) => setNu({ ...nu, role: e.target.value })}>
              {roleOptions.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
            </TextField>
            <Alert severity="info" variant="outlined">
              A temporary password is generated on creation. The user must change it on first login.
            </Alert>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" startIcon={<Add />} disabled={!nu.username || !nu.role} onClick={create}>
            Create
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
}
