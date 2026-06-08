import { useEffect, useState } from "react";

export type StreamStatus = "idle" | "open" | "closed";

/** Subscribe to a backend WebSocket; returns the latest parsed message + status.
 * Pass null to stay idle (e.g. stream not running). */
export function useStream<T = unknown>(path: string | null): { last: T | null; status: StreamStatus } {
  const [last, setLast] = useState<T | null>(null);
  const [status, setStatus] = useState<StreamStatus>("idle");

  useEffect(() => {
    if (!path) {
      setStatus("idle");
      return;
    }
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}${path}`);
    ws.onopen = () => setStatus("open");
    ws.onmessage = (e) => {
      try {
        setLast(JSON.parse(e.data));
      } catch {
        /* ignore non-JSON frames */
      }
    };
    ws.onclose = () => setStatus("closed");
    return () => ws.close();
  }, [path]);

  return { last, status };
}
