import { useEffect, useRef, useState } from "react";

export type StreamStatus = "idle" | "open" | "closed";

interface StreamOptions<T> {
  /** Called for EVERY frame, synchronously in the socket handler. Use this to accumulate
   * (e.g. append every test-result) — `last` alone is lossy because React batches state
   * updates, so a burst of frames collapses into far fewer `[last]` effect runs. */
  onMessage?: (msg: T) => void;
}

/** Subscribe to a backend WebSocket. Returns the latest parsed message + status; pass an
 * `onMessage` callback to receive every frame without loss. Pass null path to stay idle. */
export function useStream<T = unknown>(
  path: string | null,
  opts: StreamOptions<T> = {},
): { last: T | null; status: StreamStatus } {
  const [last, setLast] = useState<T | null>(null);
  const [status, setStatus] = useState<StreamStatus>("idle");

  // Hold the latest callback in a ref so a new closure each render never re-subscribes
  // (which would drop the socket). The socket effect depends only on `path`.
  const onMessageRef = useRef(opts.onMessage);
  onMessageRef.current = opts.onMessage;

  useEffect(() => {
    if (!path) {
      setStatus("idle");
      return;
    }
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}${path}`);
    ws.onopen = () => setStatus("open");
    ws.onmessage = (e) => {
      let msg: T;
      try {
        msg = JSON.parse(e.data) as T;
      } catch {
        return; /* ignore non-JSON frames */
      }
      onMessageRef.current?.(msg);   // every frame, synchronous — no batching loss
      setLast(msg);                  // latest, for "show the newest value" consumers
    };
    ws.onclose = () => setStatus("closed");
    return () => ws.close();
  }, [path]);

  return { last, status };
}
