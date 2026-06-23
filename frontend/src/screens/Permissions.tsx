/** Permissions matrix — role × permission grid with allow/disallow toggles.
 *
 * Edits the role→permission map (backend merges over config; resolve-at-login).
 * super_admin is protected (read-only, always full). Gated AUTH.MANAGE_ROLES. */
import { LockPerson, Save } from "@mui/icons-material";
import {
  Alert, Box, Button, Checkbox, Chip, Stack, Table, TableBody, TableCell,
  TableHead, TableRow, Typography,
} from "@mui/material";
import { Fragment, useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import { PageHeader, Section } from "../components/ui";

interface Perm { key: string; domain: string; label: string; description: string }
interface RoleRow { role: string; protected: boolean; permissions: string[] }

export function Permissions() {
  const [perms, setPerms] = useState<Perm[]>([]);
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [grant, setGrant] = useState<Record<string, Set<string>>>({});   // role -> granted keys
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = () => {
    api.get("/auth/roles/matrix").then((m) => {
      setPerms(m.permissions);
      setRoles(m.roles);
      const g: Record<string, Set<string>> = {};
      m.roles.forEach((r: RoleRow) => { g[r.role] = new Set(r.permissions); });
      setGrant(g); setDirty(new Set());
    }).catch((e) => setError(e.message));
  };
  useEffect(load, []);

  // permissions grouped by domain (rows), preserving catalog order
  const groups = useMemo(() => {
    const out: { domain: string; items: Perm[] }[] = [];
    for (const p of perms) {
      const g = out.find((x) => x.domain === p.domain) || (out.push({ domain: p.domain, items: [] }), out[out.length - 1]);
      g.items.push(p);
    }
    return out;
  }, [perms]);

  const editable = roles.filter((r) => !r.protected);

  const toggle = (role: string, key: string) => {
    setGrant((prev) => {
      const next = new Set(prev[role]);
      next.has(key) ? next.delete(key) : next.add(key);
      return { ...prev, [role]: next };
    });
    setDirty((d) => new Set(d).add(role));
  };

  const save = async () => {
    setBusy(true); setError(null); setNotice(null);
    try {
      for (const role of dirty) {
        await api.put(`/auth/roles/${role}`, { permissions: [...grant[role]] });
      }
      setNotice(`Saved ${dirty.size} role(s). Users get the new permissions on their next login.`);
      load();
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Box>
      <PageHeader title="Permissions" subtitle="Role → permission matrix"
        actions={<Button variant="contained" startIcon={<Save />} disabled={busy || dirty.size === 0} onClick={save}>
          Save changes{dirty.size ? ` (${dirty.size})` : ""}
        </Button>} />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}
      <Alert severity="info" sx={{ mb: 2 }}>
        Changes apply at each user's <b>next login</b> (permissions are resolved at sign-in).
        <b> super_admin</b> is protected and always holds every permission.
      </Alert>

      <Section bodyPad={0}>
        <Box sx={{ overflowX: "auto" }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell sx={{ minWidth: 280, fontWeight: 700 }}>Permission</TableCell>
                {roles.map((r) => (
                  <TableCell key={r.role} align="center" sx={{ fontWeight: 700, whiteSpace: "nowrap" }}>
                    <Stack alignItems="center" spacing={0.25}>
                      <span>{r.role}</span>
                      {r.protected && <Chip size="small" icon={<LockPerson sx={{ fontSize: 12 }} />} label="protected" sx={{ height: 18 }} />}
                    </Stack>
                  </TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {groups.map((g) => (
                <Fragment key={g.domain}>
                  <TableRow sx={{ bgcolor: "action.hover" }}>
                    <TableCell colSpan={roles.length + 1} sx={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", fontSize: 12 }}>
                      {g.domain}
                    </TableCell>
                  </TableRow>
                  {g.items.map((p) => (
                    <TableRow key={p.key} hover>
                      <TableCell>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>{p.label}</Typography>
                        <Typography variant="caption" color="text.secondary">{p.description}</Typography>
                      </TableCell>
                      {roles.map((r) => (
                        <TableCell key={r.role} align="center" sx={{ p: 0.25 }}>
                          <Checkbox size="small" checked={Boolean(grant[r.role]?.has(p.key))}
                            disabled={r.protected} onChange={() => toggle(r.role, p.key)}
                            inputProps={{ "aria-label": `${r.role}:${p.key}` }} />
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </Box>
      </Section>

      {editable.length === 0 && <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>No editable roles.</Typography>}
    </Box>
  );
}
