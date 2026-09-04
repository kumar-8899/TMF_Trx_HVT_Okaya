import {
  CheckCircleOutline, ErrorOutlineOutlined, Inventory2Outlined, MemoryOutlined,
  PlayCircleOutline, StorageOutlined, SystemUpdateAlt, TimerOutlined, TrendingUpOutlined,
  TuneOutlined, WarningAmberOutlined, WifiOffOutlined,
} from "@mui/icons-material";
import { Box, Button, Grid, Paper, Stack, Typography, useTheme } from "@mui/material";
import { useEffect, useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageHeader, Section, StatusChip, StatusDot, statusKind } from "../components/ui";
import { MONO_STACK } from "../theme/theme";

// --- types --------------------------------------------------------------------

interface ModuleRow { id: string; status: string; reason: string; display_name: string }
interface InstanceRow { id: string; library?: string; state: string; simulated?: boolean }
interface WeekKpis {
  runs: number; passed: number; failed: number; yield: number;
  units: number; fpy: number; avg_cycle_s: number;
}
interface WeekPoint { date: string; pass: number; fail: number }

const INSTANCE_KIND: Record<string, "pass" | "fail" | "running" | "idle"> = {
  connected: "pass", faulted: "fail", reconnecting: "running",
  connecting: "running", disconnected: "idle", skipped: "idle",
};

// A short, calm severity accent — not the full traffic-light palette, so the
// attention band reads as "things to look at", not an alarm wall.
type Severity = "critical" | "warning";

interface Attn {
  key: string; severity: Severity; icon: React.ReactNode; title: string;
  detail: string; to?: string; cta?: string;
}

function sevenDaysAgo(): number {
  const d = new Date(); d.setHours(0, 0, 0, 0);
  return d.getTime() / 1000 - 6 * 86400;
}

// --- stat tile ------------------------------------------------------------------

function KpiTile({
  icon, label, value, suffix, accent,
}: { icon: React.ReactNode; label: string; value: React.ReactNode; suffix?: string; accent: string }) {
  return (
    <Paper sx={{ p: 2, height: "100%", position: "relative", overflow: "hidden" }}>
      <Box sx={{ position: "absolute", top: 0, left: 0, right: 0, height: 3, bgcolor: accent }} />
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
        <Typography variant="caption" color="text.secondary"
          sx={{ textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600 }}>
          {label}
        </Typography>
        <Box sx={{ color: accent, display: "flex", opacity: 0.85 }}>{icon}</Box>
      </Stack>
      <Typography sx={{ mt: 0.5, fontFamily: MONO_STACK, fontWeight: 700, lineHeight: 1.15 }} variant="h4">
        {value}
        {suffix && <Typography component="span" variant="h6" color="text.secondary" sx={{ ml: 0.5 }}>{suffix}</Typography>}
      </Typography>
    </Paper>
  );
}

// --- attention card ---------------------------------------------------------------

function AttentionCard({ item }: { item: Attn }) {
  const t = useTheme();
  const color = item.severity === "critical" ? t.palette.status.fail : t.palette.status.running;
  const card = (
    <Paper
      sx={{
        p: 2, height: "100%", display: "flex", gap: 1.5, alignItems: "flex-start",
        borderLeft: `4px solid ${color}`,
        transition: "transform .15s",
        ...(item.to && { cursor: "pointer", "&:hover": { transform: "translateY(-2px)" } }),
      }}
    >
      <Box sx={{ color, display: "flex", mt: 0.25 }}>{item.icon}</Box>
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Typography fontWeight={600}>{item.title}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>{item.detail}</Typography>
        {item.cta && (
          <Typography variant="caption" sx={{ color, fontWeight: 600, mt: 0.75, display: "block" }}>
            {item.cta} →
          </Typography>
        )}
      </Box>
    </Paper>
  );
  return item.to
    ? <RouterLink to={item.to} style={{ textDecoration: "none", color: "inherit" }}>{card}</RouterLink>
    : card;
}

// --- page ---------------------------------------------------------------------

export function Dashboard() {
  const t = useTheme();
  const { can } = useAuth();

  const [modules, setModules] = useState<ModuleRow[]>([]);
  const [ready, setReady] = useState<boolean | null>(null);
  const [stationLinks, setStationLinks] = useState<Record<string, string>>({});
  const [version, setVersion] = useState("");
  const [instances, setInstances] = useState<InstanceRow[]>([]);
  const [week, setWeek] = useState<{ configured: boolean; kpis: WeekKpis; daily: WeekPoint[] } | null>(null);
  const [updateAvailable, setUpdateAvailable] = useState<{ tag?: string; version?: string } | null>(null);

  useEffect(() => {
    api.get("/modules/status").then((s) => setModules(s.modules || [])).catch(() => {});
    api.get("/healthz").then((h) => setVersion(h.version || "")).catch(() => {});

    api.get("/readyz").then((r) => { setReady(Boolean(r.ready)); setStationLinks(r.stations || {}); })
      .catch((e: unknown) => {
        setReady(false);
        if (e instanceof ApiError && e.body) setStationLinks(e.body.stations || {});
      });

    api.get("/variables/instances").then(setInstances).catch(() => {});

    const since = sevenDaysAgo();
    api.get(`/reports/analytics/dashboard?since=${since}`).then((d) => {
      setWeek({ configured: Boolean(d.configured), kpis: d.kpis, daily: d.passfail_daily || [] });
    }).catch(() => {});

    if (can("SYSTEM.SETTINGS")) {
      api.get("/update/offers").then((o) => {
        const applicable = (o.offers || []).find((x: any) => x.verdict?.applicable);
        if (applicable) setUpdateAvailable({ version: applicable.version });
      }).catch(() => {});
    }
  }, [can]);

  const skippedModules = useMemo(() => modules.filter((m) => m.status !== "loaded"), [modules]);
  const disconnected = useMemo(
    () => instances.filter((i) => !["connected", "skipped"].includes(i.state)),
    [instances],
  );
  const offlineStations = useMemo(
    () => Object.entries(stationLinks).filter(([, v]) => v !== "online").map(([k]) => k),
    [stationLinks],
  );

  const attention: Attn[] = useMemo(() => {
    const items: Attn[] = [];
    if (updateAvailable) {
      items.push({
        key: "update", severity: "warning", icon: <SystemUpdateAlt />,
        title: "Application update available",
        detail: `Version ${updateAvailable.version} is ready to review and install.`,
        to: "/settings", cta: "Open Settings → Updates",
      });
    }
    if (disconnected.length > 0) {
      items.push({
        key: "instruments", severity: "critical", icon: <MemoryOutlined />,
        title: `${disconnected.length} instrument${disconnected.length > 1 ? "s" : ""} not connected`,
        detail: disconnected.slice(0, 3).map((i) => i.id).join(", ")
          + (disconnected.length > 3 ? `, +${disconnected.length - 3} more` : ""),
        to: "/config/instruments", cta: "Open Config → Instruments",
      });
    }
    if (offlineStations.length > 0) {
      items.push({
        key: "bridge", severity: "critical", icon: <WifiOffOutlined />,
        title: `Bridge offline: ${offlineStations.join(", ")}`,
        detail: "The MQTT link to this station's controller is down — live values and runs will not work.",
      });
    }
    if (week && !week.configured) {
      items.push({
        key: "reportdb", severity: "warning", icon: <StorageOutlined />,
        title: "Report database not configured",
        detail: "Reports are queuing locally. Connect a database to see analytics and export history.",
        to: "/config/mes", cta: "Open Settings → Report database",
      });
    }
    if (skippedModules.length > 0) {
      items.push({
        key: "modules", severity: "warning", icon: <TuneOutlined />,
        title: `${skippedModules.length} module${skippedModules.length > 1 ? "s" : ""} not active`,
        detail: skippedModules.map((m) => `${m.display_name || m.id}${m.reason ? ` (${m.reason})` : ""}`).join(" · "),
      });
    }
    return items;
  }, [updateAvailable, disconnected, offlineStations, week, skippedModules]);

  const readyLabel = ready === null ? "checking" : ready ? "ready" : "not ready";
  const kpis = week?.kpis;

  return (
    <Box>
      <PageHeader
        title="Station"
        subtitle={version ? `Framework v${version}` : "Test & Measurement framework"}
        actions={<StatusChip label={readyLabel} size="medium" />}
      />

      <Stack spacing={3}>
        {/* Attention band — only the things that need a human, or a calm all-clear. */}
        {attention.length > 0 ? (
          <Grid container spacing={2}>
            {attention.map((item) => (
              <Grid item xs={12} sm={6} lg={4} key={item.key}>
                <AttentionCard item={item} />
              </Grid>
            ))}
          </Grid>
        ) : (
          <Paper sx={{ p: 2, display: "flex", alignItems: "center", gap: 1.5, borderLeft: `4px solid ${t.palette.status.pass}` }}>
            <Box sx={{ color: t.palette.status.pass, display: "flex" }}><CheckCircleOutline /></Box>
            <Box>
              <Typography fontWeight={600}>All systems normal</Typography>
              <Typography variant="body2" color="text.secondary">
                Instruments connected, modules active, no updates pending.
              </Typography>
            </Box>
          </Paper>
        )}

        {/* KPI hero band — last 7 days. Flex-wrap (not a 12-col Grid) so 5 tiles share the
            row evenly on wide screens and reflow cleanly on narrow ones. */}
        {kpis && (
          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
            <Box sx={{ flex: "1 1 160px", minWidth: 160 }}>
              <KpiTile icon={<PlayCircleOutline />} label="Runs (7d)" value={kpis.runs} accent={t.palette.primary.main} />
            </Box>
            <Box sx={{ flex: "1 1 160px", minWidth: 160 }}>
              <KpiTile icon={<TrendingUpOutlined />} label="Yield" value={kpis.yield} suffix="%" accent={t.palette.status.pass} />
            </Box>
            <Box sx={{ flex: "1 1 160px", minWidth: 160 }}>
              <KpiTile icon={<Inventory2Outlined />} label="Units" value={kpis.units} accent={t.palette.status.info} />
            </Box>
            <Box sx={{ flex: "1 1 160px", minWidth: 160 }}>
              <KpiTile icon={<CheckCircleOutline />} label="First-pass yield" value={kpis.fpy} suffix="%" accent={t.palette.status.pass} />
            </Box>
            <Box sx={{ flex: "1 1 160px", minWidth: 160 }}>
              <KpiTile icon={<TimerOutlined />} label="Avg cycle" value={kpis.avg_cycle_s || 0} suffix="s" accent={t.palette.status.running} />
            </Box>
          </Stack>
        )}

        {/* Trend + live instrument snapshot. */}
        <Grid container spacing={2}>
          <Grid item xs={12} md={7}>
            <Section title="Pass / fail — last 7 days" subtitle="Business-day totals from the report store">
              {week && week.configured && week.daily.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={week.daily} barGap={2}>
                    <CartesianGrid strokeDasharray="3 3" stroke={t.palette.divider} vertical={false} />
                    <XAxis dataKey="date" tick={{ fontSize: 11, fill: t.palette.text.secondary }} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: t.palette.text.secondary }} />
                    <Tooltip contentStyle={{ background: t.palette.background.paper, border: `1px solid ${t.palette.divider}` }} />
                    <Bar dataKey="pass" name="Pass" fill={t.palette.status.pass} radius={[3, 3, 0, 0]} />
                    <Bar dataKey="fail" name="Fail" fill={t.palette.status.fail} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <EmptyState
                  message={week && !week.configured ? "Report database not configured yet." : "No runs in the last 7 days."}
                  icon={<ErrorOutlineOutlined fontSize="large" />}
                />
              )}
            </Section>
          </Grid>

          <Grid item xs={12} md={5}>
            <Section title="Instruments" subtitle="Live connection state (variable engine)"
              actions={<Button component={RouterLink} to="/config/instruments" size="small" sx={{ color: "inherit" }}>Manage</Button>}>
              {instances.length === 0 ? (
                <EmptyState message="No instrument instances configured." icon={<MemoryOutlined fontSize="large" />} />
              ) : (
                <Stack spacing={1}>
                  {instances.map((s) => (
                    <Stack key={s.id} direction="row" alignItems="center" justifyContent="space-between"
                      sx={{ py: 0.75, px: 1, borderRadius: 1, "&:hover": { bgcolor: "action.hover" } }}>
                      <Stack direction="row" alignItems="center" spacing={1.25} sx={{ minWidth: 0 }}>
                        <StatusDot kind={INSTANCE_KIND[s.state] ?? "idle"} />
                        <Box sx={{ minWidth: 0 }}>
                          <Typography noWrap sx={{ fontFamily: MONO_STACK, fontSize: "0.875rem" }}>{s.id}</Typography>
                          {s.library && (
                            <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block" }}>
                              {s.library}{s.simulated ? " · simulated" : ""}
                            </Typography>
                          )}
                        </Box>
                      </Stack>
                      <StatusChip label={s.state} kind={INSTANCE_KIND[s.state] ?? statusKind(s.state)} />
                    </Stack>
                  ))}
                </Stack>
              )}
            </Section>
          </Grid>
        </Grid>

        {/* Warning wash if we cannot even tell readiness yet — keep it quiet, not alarming. */}
        {ready === false && attention.length === 0 && (
          <Stack direction="row" spacing={1} alignItems="center" color="text.secondary">
            <WarningAmberOutlined fontSize="small" />
            <Typography variant="caption">Station is not fully ready — check Diagnostics for details.</Typography>
          </Stack>
        )}
      </Stack>
    </Box>
  );
}
