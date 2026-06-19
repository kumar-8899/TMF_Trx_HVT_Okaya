import { Box, Paper, Stack, Tooltip, Typography } from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { StatusDot, statusKind } from "../ui";
import { MONO_STACK } from "../../theme/theme";

interface Analytics { total: number; passed: number; failed: number; yield: number }

function midnightEpoch(): number {
  const d = new Date(); d.setHours(0, 0, 0, 0);
  return d.getTime() / 1000;
}

/** Today's pass/fail/yield (from the report module) + a recent-runs verdict strip. */
export function TodayStrip({
  runs, onSelect, refreshKey,
}: { runs: any[]; onSelect: (id: string) => void; refreshKey?: unknown }) {
  const [a, setA] = useState<Analytics | null>(null);

  useEffect(() => {
    api.get(`/reports/analytics?since=${midnightEpoch()}`)
      .then((r) => setA(r)).catch(() => setA(null));
  }, [refreshKey]);

  const recent = runs.slice(0, 12);

  return (
    <Paper sx={{ p: 1.5 }}>
      <Stack direction="row" spacing={3} alignItems="center" flexWrap="wrap" useFlexGap>
        <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: "0.06em" }}>Today</Typography>
        <Metric label="pass" value={a?.passed ?? 0} color="success.main" />
        <Metric label="fail" value={a?.failed ?? 0} color="error.main" />
        <Metric label="total" value={a?.total ?? 0} />
        <Metric label="yield %" value={a ? Math.round(a.yield) : 0} color="info.main" />
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
