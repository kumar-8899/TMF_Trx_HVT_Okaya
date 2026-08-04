import { Box, Chip, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import { StationPicker } from "../components/StationPicker";
import { EmptyState, PageHeader, Section, StatusChip, StatusDot, statusKind } from "../components/ui";
import { useStream } from "../hooks/useStream";
import { MONO_STACK } from "../theme/theme";

interface DiagEvent { ts?: number; level?: string; subsystem?: string; message?: string; [k: string]: any }

const LEVEL_KIND: Record<string, "pass" | "fail" | "running" | "idle" | "info"> = {
  debug: "idle", info: "info", warning: "running", error: "fail", critical: "fail",
};

/** Diagnostics Viewer — live event tail + module/readiness status. Thin client over
 * existing surfaces (LOGGING bus, /modules/status, /readyz); no backend of its own. */
export function Diagnostics() {
  const [events, setEvents] = useState<DiagEvent[]>([]);
  const [level, setLevel] = useState("");
  const [subsystem, setSubsystem] = useState("");
  const [station, setStation] = useState<string | null>(null);   // multi-socket filter
  const [modules, setModules] = useState<any[]>([]);
  const [ready, setReady] = useState<{ ready: boolean; checks: Record<string, boolean> } | null>(null);

  const { last, status } = useStream<DiagEvent>("/diagnostics/stream");

  useEffect(() => {
    const tick = () => {
      api.get("/modules/status").then((s) => setModules(s.modules || [])).catch(() => {});
      api.get("/readyz").then((r) => setReady({ ready: Boolean(r.ready), checks: r.checks || {} })).catch(() => setReady({ ready: false, checks: {} }));
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => { if (last) setEvents((p) => [last, ...p].slice(0, 300)); }, [last]);

  const shown = useMemo(() => events.filter((e) =>
    (!level || e.level === level) && (!subsystem || (e.subsystem || "").includes(subsystem))
    && (!station || (e as any).station === station)), [events, level, subsystem, station]);

  return (
    <Box>
      <PageHeader title="Diagnostics" subtitle="Live event tail and station readiness"
        actions={
          <Stack direction="row" spacing={0.75} alignItems="center">
            <StatusDot kind={status === "open" ? "pass" : "idle"} />
            <Typography variant="caption" color="text.secondary">{status === "open" ? "live" : "offline"}</Typography>
          </Stack>
        } />

      <Stack direction={{ xs: "column", lg: "row" }} spacing={2}>
        <Box sx={{ flex: 2, minWidth: 0 }}>
          <Section title="Event tail" bodyPad={0}>
            <Stack direction="row" spacing={1.5} sx={{ p: 2, pb: 1.5 }} alignItems="center">
              <TextField select size="small" label="Level" value={level} onChange={(e) => setLevel(e.target.value)} sx={{ width: 130 }}>
                <MenuItem value="">All</MenuItem>
                {["debug", "info", "warning", "error", "critical"].map((l) => <MenuItem key={l} value={l}>{l}</MenuItem>)}
              </TextField>
              <TextField size="small" label="Subsystem" value={subsystem} onChange={(e) => setSubsystem(e.target.value)} />
              <StationPicker value={station} onChange={setStation} allowAll />
            </Stack>
            {shown.length === 0 ? <EmptyState message="Waiting for events…" /> : (
              <Box sx={{ maxHeight: "60vh", overflow: "auto" }}>
                <Stack>
                  {shown.map((e, i) => (
                    <Stack key={i} direction="row" spacing={1} alignItems="center" sx={{ px: 2, py: 0.6, borderBottom: "1px solid", borderColor: "divider" }}>
                      <Chip size="small" label={e.level || "info"} sx={{ height: 18, fontSize: 10 }} color={LEVEL_KIND[e.level || "info"] === "fail" ? "error" : LEVEL_KIND[e.level || "info"] === "running" ? "warning" : "default"} />
                      <Typography variant="caption" color="text.secondary" sx={{ fontFamily: MONO_STACK, minWidth: 70 }}>{e.subsystem || "—"}</Typography>
                      <Typography variant="body2" sx={{ flex: 1, minWidth: 0 }}>{e.message}</Typography>
                    </Stack>
                  ))}
                </Stack>
              </Box>
            )}
          </Section>
        </Box>

        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Section title="Readiness" sx={{ mb: 2 }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <StatusDot kind={ready?.ready ? "pass" : "fail"} />
              <Typography fontWeight={600}>{ready === null ? "checking…" : ready.ready ? "ready" : "not ready"}</Typography>
            </Stack>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {Object.entries(ready?.checks ?? {}).map(([k, v]) => (
                <Chip key={k} size="small" label={k} color={v ? "success" : "error"} variant="outlined" />
              ))}
            </Stack>
          </Section>
          <Section title="Modules" bodyPad={0}>
            <Box sx={{ p: 1.5 }}>
              <Stack spacing={0.75}>
                {modules.map((m) => (
                  <Stack key={m.id} direction="row" justifyContent="space-between" alignItems="center">
                    <Typography variant="body2" sx={{ fontFamily: MONO_STACK }}>{m.id}</Typography>
                    <StatusChip label={m.status} kind={statusKind(m.status)} />
                  </Stack>
                ))}
              </Stack>
            </Box>
          </Section>
        </Box>
      </Stack>
    </Box>
  );
}
