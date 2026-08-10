/** RunActivity — a small global "a test run is in progress" flag.
 *
 * The operator testing screen (Runs, or an app override) sets it while a run is running;
 * the shell (Layout) reads it to lock down navigation so nothing but Abort is reachable
 * (issue #6.5). While active it also traps the browser Back button and warns on tab
 * close/reload, so an operator can't wander off mid-test. */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

interface RunActivityCtx {
  active: boolean;
  setActive: (on: boolean) => void;
}

const Ctx = createContext<RunActivityCtx>({ active: false, setActive: () => {} });

export function RunActivityProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState(false);

  // Guard the browser: warn on unload, and swallow the Back button (re-push our entry)
  // while a run is active. Only mounted-effect when active, so normal nav is untouched.
  const trapped = useRef(false);
  useEffect(() => {
    if (!active) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    const onPopState = () => { window.history.pushState(null, "", window.location.href); };
    window.addEventListener("beforeunload", onBeforeUnload);
    window.addEventListener("popstate", onPopState);
    if (!trapped.current) { window.history.pushState(null, "", window.location.href); trapped.current = true; }
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      window.removeEventListener("popstate", onPopState);
      trapped.current = false;
    };
  }, [active]);

  const set = useCallback((on: boolean) => setActive(on), []);
  return <Ctx.Provider value={{ active, setActive: set }}>{children}</Ctx.Provider>;
}

export function useRunActivity() {
  return useContext(Ctx);
}
