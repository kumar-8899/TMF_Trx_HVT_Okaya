import {
  AppBar, Box, Drawer, List, ListItemButton, ListItemText, Toolbar, Typography,
} from "@mui/material";
import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { SessionPanel } from "./SessionPanel";

const DRAWER_WIDTH = 220;

interface NavItem {
  label: string;
  to: string;
  perm?: string; // undefined = always shown
}

const NAV: NavItem[] = [
  { label: "Dashboard", to: "/" },
  { label: "Recipes", to: "/recipes", perm: "RECIPE.VIEW" },
  { label: "Logs", to: "/logs", perm: "DIAGNOSTICS.VIEW" },
  { label: "Users", to: "/users", perm: "AUTH.MANAGE_USERS" },
];

export function Layout() {
  const { can } = useAuth();
  const items = NAV.filter((n) => !n.perm || can(n.perm));

  return (
    <Box sx={{ display: "flex" }}>
      <AppBar position="fixed" sx={{ zIndex: (t) => t.zIndex.drawer + 1 }}>
        <Toolbar sx={{ justifyContent: "space-between" }}>
          <Typography variant="h6">Test &amp; Measurement</Typography>
          <SessionPanel />
        </Toolbar>
      </AppBar>
      <Drawer
        variant="permanent"
        sx={{ width: DRAWER_WIDTH, flexShrink: 0,
          [`& .MuiDrawer-paper`]: { width: DRAWER_WIDTH, boxSizing: "border-box" } }}
      >
        <Toolbar />
        <List>
          {items.map((n) => (
            <ListItemButton key={n.to} component={NavLink} to={n.to}>
              <ListItemText primary={n.label} />
            </ListItemButton>
          ))}
        </List>
      </Drawer>
      <Box component="main" sx={{ flexGrow: 1, p: 3 }}>
        <Toolbar />
        <Outlet />
      </Box>
    </Box>
  );
}
