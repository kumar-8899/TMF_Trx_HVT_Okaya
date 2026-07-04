import {
  Article, Assessment, BuildOutlined, DarkMode, ExpandLess, ExpandMore, FavoriteBorder,
  GroupsOutlined, HelpOutlineOutlined, HubOutlined, LightMode, LockPersonOutlined, MemoryOutlined, MonitorHeartOutlined,
  PlayCircleOutline, QrCodeScannerOutlined, QueryStatsOutlined, ScheduleOutlined,
  ScienceOutlined, SettingsOutlined, SpaceDashboardOutlined, Speed, TuneOutlined,
} from "@mui/icons-material";
import {
  AppBar, Box, Collapse, Drawer, IconButton, List, ListItemButton, ListItemIcon,
  ListItemText, Stack, Toolbar, Tooltip, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { Link as RouterLink, NavLink, Outlet, useLocation } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useBranding } from "../hooks/useBranding";
import { useColorMode } from "../theme/ColorMode";
import { BrandMark } from "./BrandMark";
import { HelpPanel } from "./help/HelpPanel";
import { StatusDot } from "./ui";
import { SessionPanel } from "./SessionPanel";

const DRAWER_WIDTH = 232;

interface NavItem {
  label: string;
  to?: string;          // leaf has `to`; a group has `children` instead
  icon: React.ReactNode;
  perm?: string;        // undefined = always shown
  children?: NavItem[]; // cascaded menu group
}

const NAV: NavItem[] = [
  { label: "Dashboard", to: "/", icon: <SpaceDashboardOutlined /> },
  { label: "DAQ", to: "/daq", icon: <Speed /> },
  { label: "Runs", to: "/runs", icon: <PlayCircleOutline />, perm: "TEST.RUN" },
  { label: "Recipes", to: "/recipes", icon: <ScienceOutlined />, perm: "RECIPE.VIEW" },
  { label: "Reports", to: "/reports", icon: <Assessment />, perm: "REPORT.VIEW" },
  { label: "Analytics", to: "/analytics", icon: <QueryStatsOutlined />, perm: "REPORT.VIEW" },
  { label: "Health", to: "/health", icon: <FavoriteBorder />, perm: "HEALTH.VIEW" },
  { label: "Maintenance", to: "/maintenance", icon: <BuildOutlined />, perm: "HEALTH.MAINTENANCE" },
  {
    label: "Config", icon: <TuneOutlined />, perm: "CONFIG.VIEW", children: [
      { label: "Instruments", to: "/config/instruments", icon: <MemoryOutlined /> },
      { label: "Barcode", to: "/config/barcode", icon: <QrCodeScannerOutlined /> },
      { label: "Shift", to: "/config/shift", icon: <ScheduleOutlined /> },
      { label: "MES", to: "/config/mes", icon: <HubOutlined /> },
    ],
  },
  { label: "Diagnostics", to: "/diagnostics", icon: <MonitorHeartOutlined />, perm: "DIAGNOSTICS.VIEW" },
  { label: "Logs", to: "/logs", icon: <Article />, perm: "DIAGNOSTICS.VIEW" },
  { label: "Users", to: "/users", icon: <GroupsOutlined />, perm: "AUTH.MANAGE_USERS" },
  { label: "Permissions", to: "/permissions", icon: <LockPersonOutlined />, perm: "AUTH.MANAGE_ROLES" },
  { label: "Settings", to: "/settings", icon: <SettingsOutlined />, perm: "SYSTEM.RESET_DATA" },
  { label: "Help", to: "/help", icon: <HelpOutlineOutlined />, perm: "HELP.VIEW" },
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

function NavLeaf({ n, nested = false }: { n: NavItem; nested?: boolean }) {
  return (
    <ListItemButton component={NavLink} to={n.to!} end={n.to === "/"} sx={{ mb: 0.5, pl: nested ? 4 : 2 }}>
      <ListItemIcon sx={{ minWidth: 38 }}>{n.icon}</ListItemIcon>
      <ListItemText primary={n.label} primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />
    </ListItemButton>
  );
}

function NavGroup({ n, can }: { n: NavItem; can: (p: string) => boolean }) {
  const loc = useLocation();
  const kids = (n.children ?? []).filter((c) => !c.perm || can(c.perm));
  const activeInside = kids.some((c) => loc.pathname.startsWith(c.to!));
  const [open, setOpen] = useState(activeInside);
  useEffect(() => { if (activeInside) setOpen(true); }, [activeInside]);
  if (!kids.length) return null;
  return (
    <>
      <ListItemButton onClick={() => setOpen((o) => !o)} sx={{ mb: 0.5 }}>
        <ListItemIcon sx={{ minWidth: 38 }}>{n.icon}</ListItemIcon>
        <ListItemText primary={n.label} primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />
        {open ? <ExpandLess fontSize="small" /> : <ExpandMore fontSize="small" />}
      </ListItemButton>
      <Collapse in={open} unmountOnExit>
        <List disablePadding>{kids.map((c) => <NavLeaf key={c.to} n={c} nested />)}</List>
      </Collapse>
    </>
  );
}

export function Layout({ hideNav = false }: { hideNav?: boolean }) {
  const { can } = useAuth();
  const { mode, toggle } = useColorMode();
  const branding = useBranding();
  const items = NAV.filter((n) => !n.perm || can(n.perm));
  const showHelp = can("HELP.VIEW");
  const [helpOpen, setHelpOpen] = useState(false);

  // F1 or Ctrl+/ opens contextual help from anywhere.
  useEffect(() => {
    if (!showHelp) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "F1" || (e.key === "/" && (e.ctrlKey || e.metaKey))) {
        e.preventDefault(); setHelpOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showHelp]);

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <AppBar position="fixed" sx={{ zIndex: (t) => t.zIndex.drawer + 1 }}>
        <Toolbar sx={{ gap: 1 }}>
          {/* Brand returns to the dashboard — the only "back" on the drawer-less test page. */}
          <Box component={RouterLink} to="/" sx={{ mr: 1.25, display: "flex", textDecoration: "none" }}>
            <BrandMark size={28} />
          </Box>
          <Typography variant="h6" sx={{ fontWeight: 700, color: "inherit" }}>
            {branding.name}
          </Typography>
          <Box sx={{ flexGrow: 1 }} />
          <LinkStatus />
          {showHelp && (
            <Tooltip title="Help (F1)">
              <IconButton onClick={() => setHelpOpen(true)} size="small" aria-label="open help"
                sx={{ color: "rgba(255,255,255,0.85)" }}>
                <HelpOutlineOutlined fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
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
            {items.map((n) => n.children
              ? <NavGroup key={n.label} n={n} can={can} />
              : <NavLeaf key={n.to} n={n} />)}
          </List>
        </Drawer>
      )}
      <Box component="main" sx={{ flexGrow: 1, p: 3, bgcolor: "background.default" }}>
        <Toolbar />
        <Outlet />
      </Box>
      {showHelp && <HelpPanel open={helpOpen} onClose={() => setHelpOpen(false)} />}
    </Box>
  );
}
