import { useEffect, useRef, useState } from "react";

export interface ValueFrame { name: string; value: number | string | boolean | null; ts?: number }

/** Subscribe to the DAQ values WebSocket and accumulate the latest value per
 * variable name. Snapshot-on-join + live updates arrive as `{name, value, ts}`. */
export function useValues(path: string | null = "/instruments/values/ws"): Record<string, ValueFrame> {
  const [values, setValues] = useState<Record<string, ValueFrame>>({});
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!path) return;
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}${path}`);
    wsRef.current = ws;
    ws.onmessage = (e) => {
      try {
        const f: ValueFrame = JSON.parse(e.data);
        if (f && f.name) setValues((prev) => ({ ...prev, [f.name]: f }));
      } catch {
        /* ignore non-JSON frames */
      }
    };
    return () => ws.close();
  }, [path]);

  return values;
}
