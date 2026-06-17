import { createTheme, type Theme } from "@mui/material/styles";

export type Mode = "light" | "dark";

// Semantic status colors — used by StatusChip and any status dot/lamp. Kept
// distinct from the green brand accent so "running/amber" never reads as a CTA.
export interface StatusPalette {
  pass: string;
  fail: string;
  running: string;
  idle: string;
  info: string;
}

// Augment MUI's palette so theme.palette.status / .appBar / .sectionHeader are
// typed everywhere.
declare module "@mui/material/styles" {
  interface Palette {
    status: StatusPalette;
    appBar: string;
    sectionHeader: string;
    onNavy: string;
  }
  interface PaletteOptions {
    status?: StatusPalette;
    appBar?: string;
    sectionHeader?: string;
    onNavy?: string;
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

// "Instrument console" palette: light blue-grey canvas, dark-navy chrome, dark
// green primary CTAs, crimson destructive, amber accent.
const LIGHT = {
  bgDefault: "#E8EEF4",
  bgPaper: "#FFFFFF",
  appBar: "#1C2A3A",
  sectionHeader: "#1E3A5F",
  onNavy: "#FFFFFF",
  divider: "#D1D9E0",
  textPrimary: "#1C2A3A",
  textSecondary: "#6B7A8F",
  primary: { main: "#1A6B3C", light: "#1E7A45", dark: "#155C32", contrast: "#FFFFFF" },
  error: { main: "#9B1C1C", light: "#B23A3A", dark: "#7E1414", contrast: "#FFFFFF" },
  warning: { main: "#E8A020", light: "#F0B450", dark: "#C9870F", contrast: "#3A2A00" },
  info: { main: "#185FA5", light: "#3B7CBE", dark: "#124B82", contrast: "#FFFFFF" },
  cardShadow: "0 1px 3px rgba(16,42,67,0.08)",
  status: { pass: "#2E8B4F", fail: "#C0392B", running: "#C9870F", idle: "#6B7A8F", info: "#185FA5" },
};

const DARK = {
  bgDefault: "#0E1722",
  bgPaper: "#15212E",
  appBar: "#0A111B",
  sectionHeader: "#16293E",
  onNavy: "#E6EDF3",
  divider: "rgba(255,255,255,0.09)",
  textPrimary: "#E6EDF3",
  textSecondary: "#93A1B0",
  primary: { main: "#1E9E57", light: "#34B86C", dark: "#157A42", contrast: "#04210F" },
  error: { main: "#D35450", light: "#E07471", dark: "#B23A3A", contrast: "#1A0000" },
  warning: { main: "#E8A020", light: "#F0B450", dark: "#C9870F", contrast: "#241900" },
  info: { main: "#2D7DD2", light: "#5398DD", dark: "#1F5FA0", contrast: "#001020" },
  cardShadow: "0 1px 2px rgba(0,0,0,0.45)",
  status: { pass: "#4CAF50", fail: "#E5736E", running: "#E8A020", idle: "#7C8A99", info: "#4FA0E0" },
};

export function makeTheme(mode: Mode): Theme {
  const c = mode === "dark" ? DARK : LIGHT;
  const hover = mode === "dark" ? "rgba(255,255,255,0.04)" : "rgba(28,42,58,0.035)";
  return createTheme({
    palette: {
      mode,
      primary: { main: c.primary.main, light: c.primary.light, dark: c.primary.dark, contrastText: c.primary.contrast },
      error: { main: c.error.main, light: c.error.light, dark: c.error.dark, contrastText: c.error.contrast },
      warning: { main: c.warning.main, light: c.warning.light, dark: c.warning.dark, contrastText: c.warning.contrast },
      info: { main: c.info.main, light: c.info.light, dark: c.info.dark, contrastText: c.info.contrast },
      success: { main: c.status.pass, contrastText: "#FFFFFF" },
      background: { default: c.bgDefault, paper: c.bgPaper },
      divider: c.divider,
      text: { primary: c.textPrimary, secondary: c.textSecondary },
      status: c.status,
      appBar: c.appBar,
      sectionHeader: c.sectionHeader,
      onNavy: c.onNavy,
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
          "*::-webkit-scrollbar-thumb": { backgroundColor: c.divider, borderRadius: 8 },
        },
      },
      MuiPaper: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: {
            backgroundImage: "none",
            border: `1px solid ${c.divider}`,
            boxShadow: c.cardShadow,
          },
        },
      },
      MuiAppBar: {
        defaultProps: { elevation: 0, color: "default" },
        styleOverrides: {
          root: {
            backgroundColor: c.appBar,
            color: c.onNavy,
            border: "none",
            borderBottom: `1px solid ${mode === "dark" ? c.divider : "rgba(0,0,0,0.2)"}`,
            backgroundImage: "none",
            boxShadow: "none",
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
        styleOverrides: {
          root: { textTransform: "none", borderRadius: 8, fontWeight: 600 },
          containedPrimary: { boxShadow: "inset 0 -2px 0 rgba(0,0,0,0.12)" },
          containedError: { boxShadow: "inset 0 -2px 0 rgba(0,0,0,0.18)" },
        },
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
            backgroundColor: mode === "dark" ? "rgba(255,255,255,0.02)" : "#F5F7FA",
            borderBottom: `1px solid ${c.divider}`,
          },
          root: { borderBottom: `1px solid ${c.divider}` },
        },
      },
      MuiTableRow: {
        styleOverrides: { root: { "&:hover": { backgroundColor: hover } } },
      },
      MuiListItemButton: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            marginInline: 8,
            "&.active": {
              backgroundColor: mode === "dark" ? "rgba(30,158,87,0.16)" : "rgba(26,107,60,0.10)",
              color: c.primary.main,
              "& .MuiListItemIcon-root": { color: c.primary.main },
            },
          },
        },
      },
    },
  });
}
