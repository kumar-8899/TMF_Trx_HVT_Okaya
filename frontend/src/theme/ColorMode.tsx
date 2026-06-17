import { CssBaseline, ThemeProvider } from "@mui/material";
import { createContext, useCallback, useContext, useMemo, useState } from "react";

import { makeTheme, type Mode } from "./theme";

const KEY = "tmf.colormode";

interface ColorModeValue {
  mode: Mode;
  toggle: () => void;
}

const ColorModeCtx = createContext<ColorModeValue>({ mode: "dark", toggle: () => {} });

export function useColorMode(): ColorModeValue {
  return useContext(ColorModeCtx);
}

export function ColorModeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setMode] = useState<Mode>(() => {
    const saved = typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null;
    return saved === "light" || saved === "dark" ? saved : "dark";
  });

  const toggle = useCallback(() => {
    setMode((m) => {
      const next: Mode = m === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(KEY, next);
      } catch {
        /* ignore storage failures (private mode, tests) */
      }
      return next;
    });
  }, []);

  const theme = useMemo(() => makeTheme(mode), [mode]);

  return (
    <ColorModeCtx.Provider value={{ mode, toggle }}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </ThemeProvider>
    </ColorModeCtx.Provider>
  );
}
