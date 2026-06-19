import { Box, Paper, Stack, Tooltip, Typography } from "@mui/material";
import { useMemo } from "react";

import { StatusDot, statusKind } from "../ui";
import { MONO_STACK } from "../../theme/theme";

function midnightEpoch(): number {
  const d = new Date(); d.setHours(0, 0, 0, 0);
  return d.getTime() / 1000;
}

/** Today's pass/fail/yield + a recent-runs verdict strip — computed from the run
 * records so the counts increment the moment a run finishes. */
export function TodayStrip({ runs, onSelect }: { runs: any[]; onSelect: (id: string) => void }) {
  const counts = useMemo(() => {
    const since = midnightEpoch();
    let pass = 0, fail = 0, total = 0;
    for (const r of runs) {
      const d = r.data ?? {};
      const ts = d.finished_ts ?? 0;
      if (d.status !== "finished" || ts < since) continue;
      const res = String(d.result || "").toUpperCase();
      total += 1;
      if (res === "PASS") pass += 1;
      else if (res === "FAIL") fail += 1;
    }
    const denom = pass + fail;
    return { pass, fail, total, yield: denom ? Math.round((pass / denom) * 100) : 0 };
  }, [runs]);

  const recent = runs.slice(0, 12);

  return (
    <Paper sx={{ p: 1.5 }}>
      <Stack direction="row" spacing={3} alignItems="center" flexWrap="wrap" useFlexGap>
        <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: "0.06em" }}>Today</Typography>
        <Metric label="pass" value={counts.pass} color="success.main" />
        <Metric label="fail" value={counts.fail} color="error.main" />
        <Metric label="total" value={counts.total} />
        <Metric label="yield %" value={counts.yield} color="info.main" />
        <Box sx={{ flexGrow: 1 }} />
        <Stack direction="row" spacing={0.5} alignItems="center">
          {recent.map((r) => {
            const d = r.data ?? {};
            const s = d.result || d.status || "";
            return (
              <Tooltip key={r.id} title={`${r.id} · ${s}`}>
                <Box onClick={() => onSelect(r.id)} sx={{ cursor: "pointer" }}>
                  <StatusDot kind={statusKind(s)} />
                </Box>
              </Tooltip>
            );
          })}
        </Stack>
      </Stack>
    </Paper>
  );
}

function Metric({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <Stack direction="row" spacing={0.75} alignItems="baseline">
      <Typography sx={{ fontFamily: MONO_STACK, fontWeight: 700, fontSize: 20, color: color || "text.primary" }}>{value}</Typography>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
    </Stack>
  );
}
