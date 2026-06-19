import {
  Article, Assessment, DarkMode, GroupsOutlined, LightMode, PlayCircleOutline,
  QueryStatsOutlined, ScienceOutlined, SettingsOutlined, SpaceDashboardOutlined, Speed,
} from "@mui/icons-material";
import {
  AppBar, Box, Drawer, IconButton, List, ListItemButton, ListItemIcon,
  ListItemText, Stack, Toolbar, Tooltip, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { Link as RouterLink, NavLink, Outlet } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useColorMode } from "../theme/ColorMode";
import { BrandMark } from "./BrandMark";
import { StatusDot } from "./ui";
import { SessionPanel } from "./SessionPanel";

const DRAWER_WIDTH = 232;

interface NavItem {
  label: string;
  to: string;
  icon: React.ReactNode;
  perm?: string; // undefined = always shown
}

const NAV: NavItem[] = [
  { label: "Dashboard", to: "/", icon: <SpaceDashboardOutlined /> },
  { label: "DAQ", to: "/daq", icon: <Speed /> },
  { label: "Runs", to: "/runs", icon: <PlayCircleOutline />, perm: "TEST.RUN" },
  { label: "Recipes", to: "/recipes", icon: <ScienceOutlined />, perm: "RECIPE.VIEW" },
  { label: "Reports", to: "/reports", icon: <Assessment />, perm: "REPORT.VIEW" },
  { label: "Analytics", to: "/analytics", icon: <QueryStatsOutlined />, perm: "REPORT.VIEW" },
  { label: "Logs", to: "/logs", icon: <Article />, perm: "DIAGNOSTICS.VIEW" },
  { label: "Users", to: "/users", icon: <GroupsOutlined />, perm: "AUTH.MANAGE_USERS" },
  { label: "Settings", to: "/settings", icon: <SettingsOutlined />, perm: "SYSTEM.RESET_DATA" },
];

/** Poll /readyz for the station + bridge-link health lamp in the AppBar. */
function useReadyz() {
  const [state, setState] = useState<{ ready: boolean; bridge: boolean } | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = () =>
      api
        .get("/readyz")
        .then((r) => alive && setState({ ready: Boolean(r.ready), bridge: r.checks?.bridge !== false }))
        .catch(() => alive && setState({ ready: false, bridge: false }));
    tick();
    const id = setInterval(tick, 5000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  return state;
}

function LinkStatus() {
  const rz = useReadyz();
  const kind = rz === null ? "idle" : rz.ready ? "pass" : rz.bridge ? "running" : "fail";
  const label = rz === null ? "checking" : rz.ready ? "station ready" : rz.bridge ? "degraded" : "link down";
  return (
    <Tooltip title="Station readiness (/readyz)">
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ px: 1 }}>
        <StatusDot kind={kind} />
        <Typography variant="caption" sx={{ color: "rgba(255,255,255,0.72)", display: { xs: "none", md: "block" } }}>
          {label}
        </Typography>
      </Stack>
    </Tooltip>
  );
}

export function Layout({ hideNav = false }: { hideNav?: boolean }) {
  const { can } = useAuth();
  const { mode, toggle } = useColorMode();
  const items = NAV.filter((n) => !n.perm || can(n.perm));

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <AppBar position="fixed" sx={{ zIndex: (t) => t.zIndex.drawer + 1 }}>
        <Toolbar sx={{ gap: 1 }}>
          {/* Brand returns to the dashboard — the only "back" on the drawer-less test page. */}
          <Box component={RouterLink} to="/" sx={{ mr: 1.25, display: "flex", textDecoration: "none" }}>
            <BrandMark size={28} />
          </Box>
          <Typography variant="h6" sx={{ fontWeight: 700, color: "inherit" }}>
            Test &amp; Measurement
          </Typography>
          <Box sx={{ flexGrow: 1 }} />
          <LinkStatus />
          <Tooltip title={mode === "dark" ? "Switch to light" : "Switch to dark"}>
            <IconButton onClick={toggle} size="small" aria-label="toggle color mode"
              sx={{ color: "rgba(255,255,255,0.85)" }}>
              {mode === "dark" ? <LightMode fontSize="small" /> : <DarkMode fontSize="small" />}
            </IconButton>
          </Tooltip>
          <SessionPanel />
        </Toolbar>
      </AppBar>
      {!hideNav && (
        <Drawer
          variant="permanent"
          sx={{ width: DRAWER_WIDTH, flexShrink: 0,
            [`& .MuiDrawer-paper`]: { width: DRAWER_WIDTH, boxSizing: "border-box" } }}
        >
          <Toolbar />
          <List sx={{ py: 1 }}>
            {items.map((n) => (
              <ListItemButton key={n.to} component={NavLink} to={n.to} end={n.to === "/"} sx={{ mb: 0.5 }}>
                <ListItemIcon sx={{ minWidth: 38 }}>{n.icon}</ListItemIcon>
                <ListItemText primary={n.label} primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />
              </ListItemButton>
            ))}
          </List>
        </Drawer>
      )}
      <Box component="main" sx={{ flexGrow: 1, p: 3, bgcolor: "background.default" }}>
        <Toolbar />
        <Outlet />
      </Box>
    </Box>
  );
}
