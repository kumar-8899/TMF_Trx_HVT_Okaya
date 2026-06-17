import {
  Article, Assessment, GroupsOutlined, Hub, MemoryOutlined, PlayCircleOutline,
  ScienceOutlined, Speed,
} from "@mui/icons-material";
import { Box, Grid, Paper, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";

import { api } from "../api/client";
import { EmptyState, PageHeader, Section, StatusChip, statusKind } from "../components/ui";

interface ModuleRow {
  id: string;
  status: string;
  reason: string;
  display_name: string;
}

const MODULE_ICON: Record<string, React.ReactNode> = {
  daq: <Speed />, runs: <PlayCircleOutline />, recipe: <ScienceOutlined />,
  report: <Assessment />, logs: <Article />, auth: <GroupsOutlined />, hello: <Hub />,
};

const MODULE_LINK: Record<string, string> = {
  daq: "/daq", runs: "/runs", recipe: "/recipes", report: "/reports",
  logs: "/logs", auth: "/users",
};

function Stat({ label, value, kind }: { label: string; value: React.ReactNode; kind?: string }) {
  return (
    <Paper sx={{ p: 2, flex: 1, minWidth: 140 }}>
      <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {label}
      </Typography>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mt: 0.5 }}>
        <Typography variant="h5">{value}</Typography>
        {kind && <StatusChip label={kind} />}
      </Stack>
    </Paper>
  );
}

export function Dashboard() {
  const [modules, setModules] = useState<ModuleRow[]>([]);
  const [ready, setReady] = useState<boolean | null>(null);
  const [version, setVersion] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get("/modules/status").then((s) => setModules(s.modules || [])).catch((e) => setError(e.message));
    api.get("/readyz").then((r) => setReady(Boolean(r.ready))).catch(() => setReady(false));
    api.get("/healthz").then((h) => setVersion(h.version || "")).catch(() => {});
  }, []);

  const loaded = modules.filter((m) => m.status === "loaded").length;
  const readyLabel = ready === null ? "checking" : ready ? "ready" : "not ready";

  return (
    <Box>
      <PageHeader title="Station" subtitle={version ? `Backend v${version}` : "Test & Measurement framework"} />

      <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap sx={{ mb: 3 }}>
        <Stat label="Readiness" value="" kind={readyLabel} />
        <Stat label="Modules loaded" value={`${loaded}/${modules.length || 0}`} />
        <Stat label="Skipped" value={modules.length - loaded} />
      </Stack>

      <Section title="Modules" subtitle="Activation result from the module gate">
        {modules.length === 0 ? (
          <EmptyState message={error || "No module status yet."} icon={<MemoryOutlined fontSize="large" />} />
        ) : (
          <Grid container spacing={2}>
            {modules.map((m) => {
              const link = MODULE_LINK[m.id];
              const card = (
                <Paper
                  sx={{
                    p: 2, height: "100%", transition: "border-color .15s, transform .15s",
                    ...(link && {
                      cursor: "pointer",
                      "&:hover": { borderColor: "primary.main", transform: "translateY(-2px)" },
                    }),
                  }}
                >
                  <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
                    <Stack direction="row" spacing={1.5} alignItems="center">
                      <Box sx={{ color: "primary.light", display: "flex" }}>
                        {MODULE_ICON[m.id] ?? <MemoryOutlined />}
                      </Box>
                      <Typography fontWeight={600}>{m.display_name || m.id}</Typography>
                    </Stack>
                    <StatusChip label={m.status} kind={statusKind(m.status)} />
                  </Stack>
                  {m.reason && (
                    <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
                      {m.reason}
                    </Typography>
                  )}
                </Paper>
              );
              return (
                <Grid item xs={12} sm={6} md={4} key={m.id}>
                  {link ? (
                    <RouterLink to={link} style={{ textDecoration: "none", color: "inherit" }}>{card}</RouterLink>
                  ) : card}
                </Grid>
              );
            })}
          </Grid>
        )}
      </Section>
    </Box>
  );
}
