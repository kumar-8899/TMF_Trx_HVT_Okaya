/** The PC's test sockets, learned once from /modules/status (MULTI_STATION.md §6).
 * `multi` is false for a single-socket deployment — the UI then hides all station
 * chrome and behaves like a single-station system (the whole point of §1). */
import { useEffect, useState } from "react";

import { api } from "../api/client";

let cache: string[] | null = null;

export function useStations(): { stations: string[]; multi: boolean } {
  const [stations, setStations] = useState<string[]>(cache ?? []);
  useEffect(() => {
    if (cache) return;
    api.get("/modules/status")
      .then((r) => { cache = r.stations || []; setStations(cache!); })
      .catch(() => {});
  }, []);
  return { stations, multi: stations.length > 1 };
}
