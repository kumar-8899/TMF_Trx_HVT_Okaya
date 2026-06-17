import { createTheme, type Theme } from "@mui/material/styles";

export type Mode = "light" | "dark";

// Semantic status colors — used by StatusChip and any status dot/lamp. Kept
// distinct from the teal brand accent so "running/amber" never reads as a link.
export interface StatusPalette {
  pass: string;
  fail: string;
  running: string;
  idle: string;
  info: string;
}

// Augment MUI's palette so theme.palette.status is typed everywhere.
declare module "@mui/material/styles" {
  interface Palette {
    status: StatusPalette;
  }
  interface PaletteOptions {
    status?: StatusPalette;
  }
}

const FONT_STACK = [
  "Inter",
  "system-ui",
  "Segoe UI",
  "Roboto",
  "Helvetica",
  "Arial",
  "sans-serif",
].join(",");

export const MONO_STACK = ["JetBrains Mono", "Consolas", "Menlo", "monospace"].join(",");

const DARK = {
  bgDefault: "#0f141a",
  bgPaper: "#161d26",
  bgElevated: "#1c2530",
  divider: "rgba(255,255,255,0.09)",
  textPrimary: "#e6edf3",
  textSecondary: "#93a1b0",
  primaryMain: "#14b8a6",
  primaryLight: "#2dd4bf",
  primaryDark: "#0d9488",
  primaryContrast: "#00201c",
  status: { pass: "#22c55e", fail: "#ef4444", running: "#f59e0b", idle: "#64748b", info: "#38bdf8" },
};

const LIGHT = {
  bgDefault: "#f3f5f7",
  bgPaper: "#ffffff",
  bgElevated: "#ffffff",
  divider: "rgba(2,6,23,0.10)",
  textPrimary: "#0f172a",
  textSecondary: "#516072",
  primaryMain: "#0d9488",
  primaryLight: "#14b8a6",
  primaryDark: "#0f766e",
  primaryContrast: "#ffffff",
  status: { pass: "#16a34a", fail: "#dc2626", running: "#d97706", idle: "#64748b", info: "#0284c7" },
};

export function makeTheme(mode: Mode): Theme {
  const c = mode === "dark" ? DARK : LIGHT;
  return createTheme({
    palette: {
      mode,
      primary: {
        main: c.primaryMain,
        light: c.primaryLight,
        dark: c.primaryDark,
        contrastText: c.primaryContrast,
      },
      background: { default: c.bgDefault, paper: c.bgPaper },
      divider: c.divider,
      text: { primary: c.textPrimary, secondary: c.textSecondary },
      success: { main: c.status.pass },
      error: { main: c.status.fail },
      warning: { main: c.status.running },
      info: { main: c.status.info },
      status: c.status,
    },
    shape: { borderRadius: 10 },
    typography: {
      fontFamily: FONT_STACK,
      h4: { fontWeight: 700, letterSpacing: "-0.02em" },
      h5: { fontWeight: 700, letterSpacing: "-0.01em" },
      h6: { fontWeight: 600, letterSpacing: "-0.01em" },
      subtitle2: { fontWeight: 600 },
      button: { fontWeight: 600 },
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          "*::-webkit-scrollbar": { width: 10, height: 10 },
          "*::-webkit-scrollbar-thumb": {
            backgroundColor: c.divider,
            borderRadius: 8,
          },
        },
      },
      MuiPaper: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: {
            backgroundImage: "none",
            border: `1px solid ${c.divider}`,
          },
        },
      },
      MuiAppBar: {
        defaultProps: { elevation: 0, color: "default" },
        styleOverrides: {
          root: {
            backgroundColor: c.bgPaper,
            borderBottom: `1px solid ${c.divider}`,
            backgroundImage: "none",
          },
        },
      },
      MuiDrawer: {
        styleOverrides: {
          paper: { backgroundColor: c.bgPaper, borderRight: `1px solid ${c.divider}` },
        },
      },
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: { root: { textTransform: "none", borderRadius: 8 } },
      },
      MuiChip: {
        styleOverrides: { root: { borderRadius: 6, fontWeight: 600 } },
      },
      MuiTextField: { defaultProps: { size: "small" } },
      MuiTable: { defaultProps: { size: "small" } },
      MuiTableCell: {
        styleOverrides: {
          head: {
            textTransform: "uppercase",
            fontSize: "0.7rem",
            letterSpacing: "0.06em",
            color: c.textSecondary,
            fontWeight: 700,
            borderBottom: `1px solid ${c.divider}`,
          },
          root: { borderBottom: `1px solid ${c.divider}` },
        },
      },
      MuiTableRow: {
        styleOverrides: {
          root: { "&:hover": { backgroundColor: mode === "dark" ? "rgba(255,255,255,0.03)" : "rgba(2,6,23,0.025)" } },
        },
      },
      MuiListItemButton: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            marginInline: 8,
            "&.active": {
              backgroundColor: mode === "dark" ? "rgba(20,184,166,0.16)" : "rgba(13,148,136,0.12)",
              color: c.primaryLight,
              "& .MuiListItemIcon-root": { color: c.primaryLight },
            },
          },
        },
      },
    },
  });
}
