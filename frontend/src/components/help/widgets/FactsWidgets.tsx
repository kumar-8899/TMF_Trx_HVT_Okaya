/** Widgets backed by the generated facts (`docs/generated/facts.json`) plus the live app:
 *   tmf:facts <version|modules|capabilities|ops|routes|skills>
 *   tmf:permissions-matrix   role × permission grid (wildcards expanded like the backend does)
 *   tmf:step-types           step-type browser with each type's parameter schema
 *   tmf:changelog            release feed, filterable by bump, expandable
 *   tmf:live-app             THIS app's loaded modules + step types (works in a fork too) */
import {
  Alert, Box, Chip, CircularProgress, Collapse, Stack, Table, TableBody, TableCell, TableHead,
  TableRow, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import { useEffect, useState, type ReactNode } from "react";

import { api } from "../../../api/client";
import { hasPermission } from "../../../auth/permissions";
import { Markdown } from "../Markdown";
import { type Facts, useFacts } from "./facts";

function Gate({ children }: { children: (f: Facts) => ReactNode }) {
  const { facts, error } = useFacts();
  if (error) return <Alert severity="warning" sx={{ my: 1 }}>Generated facts unavailable ({error}). Run <code>python tools/gen_devguide.py</code>.</Alert>;
  if (!facts) return <CircularProgress size={18} sx={{ m: 1 }} />;
  return <>{children(facts)}</>;
}

function Grid({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <Box sx={{ overflowX: "auto", my: 1.5 }}>
      <Table size="small">
        <TableHead><TableRow>{head.map((h) => <TableCell key={h} sx={{ fontWeight: 700 }}>{h}</TableCell>)}</TableRow></TableHead>
        <TableBody>
          {rows.map((r, i) => <TableRow key={i}>{r.map((c, j) => <TableCell key={j}>{c}</TableCell>)}</TableRow>)}
        </TableBody>
      </Table>
    </Box>
  );
}

const code = (s: ReactNode) => <code>{s}</code>;

export function FactsWidget({ arg }: { arg: string }) {
  const kind = arg.trim().split(/\s+/)[0] || "version";
  return (
    <Gate>
      {(f) => {
        switch (kind) {
          case "version":
            return <Typography component="span" sx={{ fontWeight: 700 }}>v{f.framework.version}</Typography>;
          case "modules":
            return <Grid head={["Module", "Version", "Contract", "API prefix", "Depends on core", "Permissions"]}
              rows={f.modules.map((m) => [<strong key="i">{m.id}</strong>, m.version, m.contract_version, code(m.api_prefix ?? "—"),
                m.core_dependencies.join(", "), m.permissions_used.join(", ")])} />;
          case "capabilities":
            return <Grid head={["Capability", "Version", "Kind", "Methods"]}
              rows={f.capabilities.map((c) => [<strong key="i">{c.interface}</strong>, c.interface_version,
                c.scalar ? "scalar" : "non-scalar", c.methods.join(", ")])} />;
          case "ops":
            return <Grid head={["MQTT op", "Group", "Dispatch"]}
              rows={f.controller_ops.map((o) => [code(o.op), o.group, o.blocking ? "worker pool (hardware I/O)" : "inline"])} />;
          case "routes":
            return <Grid head={["Screen route", "Needs"]}
              rows={f.frontend_routes.map((r) => [code(r.path), r.permission ?? (r.role ? `role ${r.role}` : "any signed-in user")])} />;
          case "skills":
            return <Grid head={["Skill", "What it does"]}
              rows={f.skills.map((s) => [<strong key="i">{s.name}</strong>, s.description.split(". ")[0] + "."])} />;
          default:
            return <Alert severity="error">Unknown facts view <code>{kind}</code>.</Alert>;
        }
      }}
    </Gate>
  );
}

export function PermissionsMatrixWidget() {
  return (
    <Gate>
      {(f) => {
        const roles = Object.keys(f.roles);
        return (
          <Grid head={["Permission", ...roles]}
            rows={f.permissions.map((p) => [
              <span key="p"><code>{p.key}</code><Typography variant="caption" component="div" color="text.secondary">{p.label}</Typography></span>,
              ...roles.map((r) => (hasPermission(f.roles[r], p.key) ? "●" : "·")),
            ])} />
        );
      }}
    </Gate>
  );
}

export function StepTypesWidget() {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Gate>
      {(f) => (
        <Box sx={{ my: 1.5 }}>
          <Stack direction="row" flexWrap="wrap" gap={0.75}>
            {f.step_types.map((s) => (
              <Chip key={s.type_id} label={s.type_id} color={open === s.type_id ? "primary" : "default"} variant="outlined"
                onClick={() => setOpen(open === s.type_id ? null : s.type_id)} />
            ))}
          </Stack>
          {f.step_types.map((s) => (
            <Collapse key={s.type_id} in={open === s.type_id} unmountOnExit>
              <Box sx={{ mt: 1, p: 1.5, bgcolor: "action.hover", borderRadius: 1 }}>
                <Typography variant="subtitle2">{s.display_name} <Chip size="small" label={s.kind} sx={{ ml: 1 }} />
                  {s.composite && <Chip size="small" label="composite" sx={{ ml: 0.5 }} />}</Typography>
                <Typography variant="caption" component="div" sx={{ mb: 0.5 }}>
                  needs signals: {s.required_signals.join(", ") || "—"} · actions: {s.required_actions.join(", ") || "—"}
                </Typography>
                <pre style={{ margin: 0, overflowX: "auto", fontSize: 12 }}>{JSON.stringify(s.schema, null, 2)}</pre>
              </Box>
            </Collapse>
          ))}
        </Box>
      )}
    </Gate>
  );
}

export function ChangelogWidget({ arg }: { arg: string }) {
  const [bump, setBump] = useState<string>("ALL");
  const [open, setOpen] = useState<string | null>(null);
  const limit = Number(arg.trim()) || 15;
  return (
    <Gate>
      {(f) => {
        const rows = f.releases.filter((r) => bump === "ALL" || r.bump === bump).slice(0, limit);
        return (
          <Box sx={{ my: 1.5 }}>
            <ToggleButtonGroup size="small" exclusive value={bump} onChange={(_, v) => v && setBump(v)} sx={{ mb: 1 }}>
              {["ALL", "MAJOR", "MINOR", "PATCH"].map((b) => <ToggleButton key={b} value={b}>{b}</ToggleButton>)}
            </ToggleButtonGroup>
            {rows.map((r) => (
              <Box key={r.version} sx={{ borderBottom: "1px solid", borderColor: "divider", py: 0.75 }}>
                <Stack direction="row" spacing={1} alignItems="baseline" sx={{ cursor: "pointer" }}
                  onClick={() => setOpen(open === r.version ? null : r.version)}>
                  <Typography sx={{ fontWeight: 700 }}>v{r.version}</Typography>
                  <Typography variant="caption" color="text.secondary">{r.date}</Typography>
                  {r.bump && <Chip size="small" label={r.bump} color={r.bump === "PATCH" ? "default" : "primary"} variant="outlined" />}
                  <Typography variant="body2" sx={{ flex: 1 }}>{r.summary}</Typography>
                </Stack>
                <Collapse in={open === r.version} unmountOnExit><Markdown>{r.body}</Markdown></Collapse>
              </Box>
            ))}
            {rows.length === 0 && <Typography variant="body2" color="text.secondary">No releases match.</Typography>}
          </Box>
        );
      }}
    </Gate>
  );
}

interface ModuleRow { id: string; variant: string; status: string; reason?: string }

export function LiveAppWidget() {
  const [mods, setMods] = useState<ModuleRow[] | null>(null);
  const [steps, setSteps] = useState<{ type_id: string; kind: string }[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.get("/modules/status").then((r) => setMods(r.modules ?? [])).catch((e) => setErr(e.message));
    api.get("/recipes/step-types").then((r) => setSteps(Array.isArray(r) ? r : r?.step_types ?? [])).catch(() => setSteps([]));
  }, []);
  if (err) return <Alert severity="warning" sx={{ my: 1 }}>Could not read this app's live status: {err}</Alert>;
  if (!mods) return <CircularProgress size={18} sx={{ m: 1 }} />;
  return (
    <Box sx={{ my: 1.5 }}>
      <Typography variant="subtitle2">This app — modules</Typography>
      <Grid head={["Module", "Variant", "Status"]}
        rows={mods.map((m) => [<strong key="i">{m.id}</strong>, m.variant, m.status === "loaded" ? "loaded" : `skipped — ${m.reason ?? ""}`])} />
      <Typography variant="subtitle2">This app — step types (framework core + the app's own packages)</Typography>
      <Stack direction="row" flexWrap="wrap" gap={0.75} sx={{ mt: 0.5 }}>
        {(steps ?? []).map((s) => <Chip key={s.type_id} size="small" variant="outlined" label={s.type_id}
          color={s.kind === "application" ? "secondary" : "default"} />)}
      </Stack>
    </Box>
  );
}
