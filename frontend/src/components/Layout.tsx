import {
  AppsOutlined, Article, Assessment, BadgeOutlined, BuildOutlined, DarkMode, ExpandLess, ExpandMore, FavoriteBorder,
  Fullscreen, FullscreenExit,
  GroupsOutlined, HelpOutlineOutlined, HubOutlined, LightMode, LockPersonOutlined, MemoryOutlined, MenuBookOutlined, MonitorHeartOutlined,
  PlayCircleOutline, QrCodeScannerOutlined, QueryStatsOutlined, ScheduleOutlined,
  ScienceOutlined, SettingsOutlined, SpaceDashboardOutlined, TuneOutlined,
} from "@mui/icons-material";
import {
  AppBar, Box, Collapse, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon,
  ListItemText, Stack, Toolbar, Tooltip, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { Link as RouterLink, NavLink, Outlet, useLocation } from "react-router-dom";

import { api } from "../api/client";
import { APP_PAGES } from "../app/registry";
import { useAuth } from "../auth/AuthContext";
import { useBranding } from "../hooks/useBranding";
import { useRunActivity } from "./RunActivity";
import { useColorMode } from "../theme/ColorMode";
import { BrandMark } from "./BrandMark";
import { HelpPanel } from "./help/HelpPanel";
import { MesAlertDialog } from "./MesAlertDialog";
import { StatusDot } from "./ui";
import { UpdateChip } from "./UpdateChip";
import { UserMenu } from "./UserMenu";

const DRAWER_WIDTH = 232;

interface NavItem {
  label: string;
  to?: string;          // leaf has `to`; a group has `children` instead
  icon: React.ReactNode;
  perm?: string;        // undefined = always shown
  role?: string;        // restrict to a role (e.g. super_admin)
  children?: NavItem[]; // cascaded menu group
}

// Grouped into a few cascaded dropdowns to keep the drawer short (issue #6/#7 nav).
// Dashboard + Runs stay top-level (the two most-used); the rest fold into groups.
const NAV: NavItem[] = [
  { label: "Dashboard", to: "/", icon: <SpaceDashboardOutlined /> },
  { label: "Runs", to: "/runs", icon: <PlayCircleOutline />, perm: "TEST.RUN" },
  {
    label: "Operations", icon: <ScienceOutlined />, children: [
      { label: "Recipes", to: "/recipes", icon: <ScienceOutlined />, perm: "RECIPE.VIEW" },
      { label: "Reports", to: "/reports", icon: <Assessment />, perm: "REPORT.VIEW" },
      { label: "Analytics", to: "/analytics", icon: <QueryStatsOutlined />, perm: "REPORT.VIEW" },
    ],
  },
  {
    label: "Health", icon: <FavoriteBorder />, children: [
      { label: "Health", to: "/health", icon: <FavoriteBorder />, perm: "HEALTH.VIEW" },
      { label: "Maintenance", to: "/maintenance", icon: <BuildOutlined />, perm: "HEALTH.MAINTENANCE" },
    ],
  },
  {
    label: "Config", icon: <TuneOutlined />, perm: "CONFIG.VIEW", children: [
      { label: "App identity", to: "/config/branding", icon: <BadgeOutlined />, role: "super_admin" },
      { label: "Instruments", to: "/config/instruments", icon: <MemoryOutlined /> },
      { label: "Barcode", to: "/config/barcode", icon: <QrCodeScannerOutlined /> },
      { label: "Shift", to: "/config/shift", icon: <ScheduleOutlined /> },
      { label: "MES", to: "/config/mes", icon: <HubOutlined /> },
    ],
  },
  {
    label: "Administration", icon: <LockPersonOutlined />, children: [
      { label: "Users", to: "/users", icon: <GroupsOutlined />, perm: "AUTH.MANAGE_USERS" },
      { label: "Permissions", to: "/permissions", icon: <LockPersonOutlined />, perm: "AUTH.MANAGE_ROLES" },
      { label: "Settings", to: "/settings", icon: <SettingsOutlined />, perm: "SYSTEM.RESET_DATA" },
      { label: "Diagnostics", to: "/diagnostics", icon: <MonitorHeartOutlined />, perm: "DIAGNOSTICS.VIEW" },
      { label: "Logs", to: "/logs", icon: <Article />, perm: "DIAGNOSTICS.VIEW" },
    ],
  },
  // App-contributed pages (TEMPLATE.md §1.3) — one flat nav item per registered page.
  ...APP_PAGES.map((p): NavItem => (
    { label: p.navLabel, to: p.path, icon: p.navIcon ?? <AppsOutlined />, perm: p.permission }
  )),
  { label: "Portal", to: "/portal", icon: <MenuBookOutlined />, perm: "PORTAL.VIEW" },
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

/** Thin vertical separator that groups the AppBar controls into clusters. */
function NavDivider() {
  return (
    <Divider orientation="vertical" flexItem
      sx={{ my: 1.25, mx: 0.5, borderColor: "rgba(255,255,255,0.18)", display: { xs: "none", sm: "block" } }} />
  );
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

function NavGroup({ n, can, role }: { n: NavItem; can: (p: string) => boolean; role?: string }) {
  const loc = useLocation();
  const kids = (n.children ?? []).filter((c) => (!c.perm || can(c.perm)) && (!c.role || c.role === role));
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
  const { can, principal } = useAuth();
  const { mode, toggle } = useColorMode();
  const branding = useBranding();
  const { active: runActive } = useRunActivity();   // #6.5 lock nav while a run runs

  // #6.4 full-screen: a toggle in the AppBar (browsers only allow FS from a user gesture,
  // so no auto-enter). Tracks the actual fullscreen element so the icon stays honest.
  const [fs, setFs] = useState(false);
  useEffect(() => {
    const onFs = () => setFs(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);
  const toggleFs = () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else document.documentElement.requestFullscreen().catch(() => {});
  };
  const items = NAV.filter((n) => (!n.perm || can(n.perm)) && (!n.role || principal?.role === n.role));
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
          {/* Brand returns to the dashboard — the only "back" on the drawer-less test page.
              While a run is active it is inert (#6.5: only Abort is reachable). */}
          {runActive ? (
            <Box sx={{ mr: 1.25, display: "flex" }}><BrandMark size={28} /></Box>
          ) : (
            <Box component={RouterLink} to="/" sx={{ mr: 1.25, display: "flex", textDecoration: "none" }}>
              <BrandMark size={28} />
            </Box>
          )}
          {/* Client logo, top-left next to the brand (issue #7). */}
          {branding.logo_client && (
            <Box component="img" src={branding.logo_client} alt="client logo"
              sx={{ height: 30, maxWidth: 160, objectFit: "contain", mr: 1 }} />
          )}
          <Typography variant="h6" sx={{ fontWeight: 700, color: "inherit" }}>
            {branding.name}
          </Typography>
          <Box sx={{ flexGrow: 1 }} />
          {/* Exeliq logo, top-right (issue #7) — always shown when set, even during a run. */}
          {branding.logo_exeliq && (
            <Box component="img" src={branding.logo_exeliq} alt="Exeliq"
              sx={{ height: 26, maxWidth: 140, objectFit: "contain", mr: 1 }} />
          )}
          {/* Run in progress → hide everything but keep the operator on the test screen. */}
          {runActive ? (
            <Typography variant="body2" sx={{ color: "rgba(255,255,255,0.85)", fontWeight: 600, letterSpacing: "0.05em" }}>
              TEST IN PROGRESS
            </Typography>
          ) : (
            <>
              <LinkStatus />
              <NavDivider />
              {showHelp && (
                <Tooltip title="Help (F1)">
                  <IconButton onClick={() => setHelpOpen(true)} size="small" aria-label="open help"
                    sx={{ color: "rgba(255,255,255,0.85)" }}>
                    <HelpOutlineOutlined fontSize="small" />
                  </IconButton>
                </Tooltip>
              )}
              <Tooltip title={fs ? "Exit full screen" : "Full screen"}>
                <IconButton onClick={toggleFs} size="small" aria-label="toggle full screen"
                  sx={{ color: "rgba(255,255,255,0.85)" }}>
                  {fs ? <FullscreenExit fontSize="small" /> : <Fullscreen fontSize="small" />}
                </IconButton>
              </Tooltip>
              <Tooltip title={mode === "dark" ? "Switch to light" : "Switch to dark"}>
                <IconButton onClick={toggle} size="small" aria-label="toggle color mode"
                  sx={{ color: "rgba(255,255,255,0.85)" }}>
                  {mode === "dark" ? <LightMode fontSize="small" /> : <DarkMode fontSize="small" />}
                </IconButton>
              </Tooltip>
              <NavDivider />
              <UserMenu />
            </>
          )}
        </Toolbar>
      </AppBar>
      {!hideNav && (
        <Drawer
          variant="permanent"
          sx={{ width: DRAWER_WIDTH, flexShrink: 0,
            [`& .MuiDrawer-paper`]: { width: DRAWER_WIDTH, boxSizing: "border-box",
              display: "flex", flexDirection: "column" } }}
        >
          <Toolbar />
          <List sx={{ py: 1, flexGrow: 1, overflowY: "auto" }}>
            {items.map((n) => n.children
              ? <NavGroup key={n.label} n={n} can={can} role={principal?.role} />
              : <NavLeaf key={n.to} n={n} />)}
          </List>
          {/* Relaunch-to-update lives at the foot of the menu — only rendered when an
              update is staged, and never mid-run. */}
          {!runActive && <UpdateChip drawer />}
        </Drawer>
      )}
      <Box component="main" sx={{ flexGrow: 1, p: 3, bgcolor: "background.default" }}>
        <Toolbar />
        <Outlet />
      </Box>
      <MesAlertDialog />
      {showHelp && <HelpPanel open={helpOpen} onClose={() => setHelpOpen(false)} />}
    </Box>
  );
}
