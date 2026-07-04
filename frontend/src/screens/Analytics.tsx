import { useCallback, useEffect, useState } from "react";
import {
  Box, Grid, MenuItem, Paper, Stack, Tab, Tabs, TextField, Typography, useTheme,
} from "@mui/material";
import {
  Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { api } from "../api/client";
import { EmptyState, PageHeader, Section } from "../components/ui";
import { MONO_STACK } from "../theme/theme";

interface Dashboard {
  kpis: {
    runs: number; passed: number; failed: number; aborted: number; yield: number;
    units: number; fpy: number; retest_rate: number; avg_cycle_s: number; median_cycle_s: number;
  };
  fpy: { series: { date: string; p: number; ucl: number; lcl: number }[]; pbar: number };
  passfail_daily: { date: string; pass: number; fail: number }[];
  failure_pareto: { name: string; count: number; cum_pct: number }[];
  param_pareto: { name: string; count: number; cum_pct: number }[];
  by_model: { model: string; total: number; passed: number; failed: number; fpy: number }[];
  by_shift: { shift: string; total: number; passed: number; failed: number; yield: number }[];
  cycle: {
    histogram: { bin: number; count: number }[];
    imr: { points: { i: number; x: number; mr: number | null }[]; xbar: number; ucl: number; lcl: number; mr_bar: number; mr_ucl: number };
  };
  models: string[];
  operators: string[];
  shifts: string[];
}

const RANGES: Record<string, number | null> = {
  "Today": 0, "7 days": 7, "30 days": 30, "90 days": 90, "All time": null,
};

function sinceFor(label: string): number | undefined {
  const v = RANGES[label];
  if (v === null) return undefined;
  const d = new Date(); d.setHours(0, 0, 0, 0);
  return d.getTime() / 1000 - v * 86400;
}

export function Analytics() {
  const t = useTheme();
  const C = {
    pass: t.palette.status.pass, fail: t.palette.status.fail, run: t.palette.status.running,
    info: t.palette.status.info, primary: t.palette.primary.main,
    axis: t.palette.text.secondary, grid: t.palette.divider,
  };
  const [tab, setTab] = useState(0);
  const [range, setRange] = useState("30 days");
  const [model, setModel] = useState("");
  const [operator, setOperator] = useState("");
  const [shift, setShift] = useState("");
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    const q = new URLSearchParams();
    const since = sinceFor(range);
    if (since !== undefined) q.set("since", String(since));
    if (model) q.set("model", model);
    if (operator) q.set("operator", operator);
    if (shift) q.set("shift", shift);
    try { setData(await api.get(`/reports/analytics/dashboard?${q.toString()}`)); }
    catch (e: any) { setError(e.message); }
  }, [range, model, operator, shift]);

  useEffect(() => { load(); }, [load]);

  const axis = { stroke: C.axis, fontSize: 11, tickLine: false };
  const tip = {
    contentStyle: { background: t.palette.background.paper, border: `1px solid ${C.grid}`, borderRadius: 8, fontSize: 12 },
    labelStyle: { color: t.palette.text.primary },
  };

  const k = data?.kpis;

  return (
    <Box>
      <PageHeader
        title="Analytics"
        subtitle="Test quality, failures, and cycle-time insights"
        actions={
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <TextField select size="small" label="Range" value={range} onChange={(e) => setRange(e.target.value)} sx={{ width: 130 }}>
              {Object.keys(RANGES).map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
            </TextField>
            <TextField select size="small" label="Model" value={model} onChange={(e) => setModel(e.target.value)} sx={{ width: 140 }}>
              <MenuItem value="">All models</MenuItem>
              {(data?.models ?? []).map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}
            </TextField>
            {(data?.shifts?.length ?? 0) > 0 && (
              <TextField select size="small" label="Shift" value={shift} onChange={(e) => setShift(e.target.value)} sx={{ width: 140 }}>
                <MenuItem value="">All shifts</MenuItem>
                {(data?.shifts ?? []).map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
              </TextField>
            )}
            <TextField select size="small" label="Operator" value={operator} onChange={(e) => setOperator(e.target.value)} sx={{ width: 140 }}>
              <MenuItem value="">All operators</MenuItem>
              {(data?.operators ?? []).map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
            </TextField>
          </Stack>
        }
      />
      {error && <Typography color="error" sx={{ mb: 2 }}>{error}</Typography>}

      {/* KPI band */}
      {k && (
        <Grid container spacing={2} sx={{ mb: 2 }}>
          <Kpi label="First Pass Yield" value={`${k.fpy}%`} color={k.fpy >= 95 ? C.pass : k.fpy >= 85 ? C.run : C.fail} />
          <Kpi label="Yield" value={`${k.yield}%`} />
          <Kpi label="Units" value={k.units} />
          <Kpi label="Runs" value={k.runs} />
          <Kpi label="Retest rate" value={`${k.retest_rate}%`} color={k.retest_rate > 10 ? C.run : undefined} />
          <Kpi label="Avg cycle" value={`${k.avg_cycle_s}s`} />
        </Grid>
      )}

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Quality" /><Tab label="Failures" /><Tab label="Cycle time" />
      </Tabs>

      {!data ? <EmptyState message={error || "Loading…"} /> : (
        <>
          {tab === 0 && (
            <Grid container spacing={2}>
              <Grid item xs={12} lg={7}>
                <Section title="First Pass Yield — p-chart" subtitle={`Center line p̄ = ${data.fpy.pbar}%`}>
                  <ChartBox>
                    <ComposedChart data={data.fpy.series}>
                      <CartesianGrid stroke={C.grid} vertical={false} />
                      <XAxis dataKey="date" {...axis} /><YAxis domain={[0, 100]} {...axis} />
                      <Tooltip {...tip} />
                      <ReferenceLine y={data.fpy.pbar} stroke={C.info} strokeDasharray="4 3" />
                      <Line type="monotone" dataKey="ucl" stroke={C.fail} strokeDasharray="3 3" dot={false} name="UCL" />
                      <Line type="monotone" dataKey="lcl" stroke={C.fail} strokeDasharray="3 3" dot={false} name="LCL" />
                      <Line type="monotone" dataKey="p" stroke={C.primary} strokeWidth={2} name="FPY %" />
                    </ComposedChart>
                  </ChartBox>
                </Section>
              </Grid>
              <Grid item xs={12} lg={5}>
                <Section title="Pass / Fail per day">
                  <ChartBox>
                    <BarChart data={data.passfail_daily}>
                      <CartesianGrid stroke={C.grid} vertical={false} />
                      <XAxis dataKey="date" {...axis} /><YAxis {...axis} />
                      <Tooltip {...tip} /><Legend />
                      <Bar dataKey="pass" stackId="s" fill={C.pass} name="Pass" />
                      <Bar dataKey="fail" stackId="s" fill={C.fail} name="Fail" />
                    </BarChart>
                  </ChartBox>
                </Section>
              </Grid>
            </Grid>
          )}

          {tab === 1 && (
            <Grid container spacing={2}>
              <Grid item xs={12} lg={6}>
                <Section title="Failure Pareto" subtitle="First failing test, with cumulative %">
                  <ChartBox>
                    <ComposedChart data={data.failure_pareto}>
                      <CartesianGrid stroke={C.grid} vertical={false} />
                      <XAxis dataKey="name" {...axis} interval={0} angle={-20} textAnchor="end" height={60} />
                      <YAxis yAxisId="l" {...axis} /><YAxis yAxisId="r" orientation="right" domain={[0, 100]} {...axis} />
                      <Tooltip {...tip} />
                      <Bar yAxisId="l" dataKey="count" fill={C.fail} name="Failures" />
                      <Line yAxisId="r" type="monotone" dataKey="cum_pct" stroke={C.info} strokeWidth={2} name="Cumulative %" />
                    </ComposedChart>
                  </ChartBox>
                </Section>
              </Grid>
              <Grid item xs={12} lg={6}>
                <Section title="Parameter Pareto" subtitle="Most frequently failing tests">
                  <ChartBox>
                    <BarChart data={data.param_pareto} layout="vertical">
                      <CartesianGrid stroke={C.grid} horizontal={false} />
                      <XAxis type="number" {...axis} /><YAxis type="category" dataKey="name" width={120} {...axis} />
                      <Tooltip {...tip} />
                      <Bar dataKey="count" fill={C.run} name="Failures" />
                    </BarChart>
                  </ChartBox>
                </Section>
              </Grid>
              <Grid item xs={12} md={(data.by_shift?.length ?? 0) > 0 ? 6 : 12}>
                <Section title="Yield by model">
                  <ChartBox>
                    <BarChart data={data.by_model}>
                      <CartesianGrid stroke={C.grid} vertical={false} />
                      <XAxis dataKey="model" {...axis} /><YAxis {...axis} />
                      <Tooltip {...tip} /><Legend />
                      <Bar dataKey="passed" stackId="m" fill={C.pass} name="Pass" />
                      <Bar dataKey="failed" stackId="m" fill={C.fail} name="Fail" />
                    </BarChart>
                  </ChartBox>
                </Section>
              </Grid>
              {(data.by_shift?.length ?? 0) > 0 && (
                <Grid item xs={12} md={6}>
                  <Section title="Yield by shift">
                    <ChartBox>
                      <BarChart data={data.by_shift}>
                        <CartesianGrid stroke={C.grid} vertical={false} />
                        <XAxis dataKey="shift" {...axis} /><YAxis {...axis} />
                        <Tooltip {...tip} /><Legend />
                        <Bar dataKey="passed" stackId="s" fill={C.pass} name="Pass" />
                        <Bar dataKey="failed" stackId="s" fill={C.fail} name="Fail" />
                      </BarChart>
                    </ChartBox>
                  </Section>
                </Grid>
              )}
            </Grid>
          )}

          {tab === 2 && (
            <Grid container spacing={2}>
              <Grid item xs={12} lg={5}>
                <Section title="Cycle-time histogram" subtitle="seconds">
                  <ChartBox>
                    <BarChart data={data.cycle.histogram}>
                      <CartesianGrid stroke={C.grid} vertical={false} />
                      <XAxis dataKey="bin" {...axis} /><YAxis {...axis} />
                      <Tooltip {...tip} />
                      <Bar dataKey="count" fill={C.primary}>
                        {data.cycle.histogram.map((_, i) => <Cell key={i} fill={C.primary} />)}
                      </Bar>
                    </BarChart>
                  </ChartBox>
                </Section>
              </Grid>
              <Grid item xs={12} lg={7}>
                <Section title="Cycle time — I chart (individuals)" subtitle={`X̄ = ${data.cycle.imr.xbar}s · UCL ${data.cycle.imr.ucl} · LCL ${data.cycle.imr.lcl}`}>
                  <ChartBox>
                    <LineChart data={data.cycle.imr.points}>
                      <CartesianGrid stroke={C.grid} vertical={false} />
                      <XAxis dataKey="i" {...axis} /><YAxis {...axis} />
                      <Tooltip {...tip} />
                      <ReferenceLine y={data.cycle.imr.xbar} stroke={C.info} strokeDasharray="4 3" />
                      <ReferenceLine y={data.cycle.imr.ucl} stroke={C.fail} strokeDasharray="3 3" />
                      <ReferenceLine y={data.cycle.imr.lcl} stroke={C.fail} strokeDasharray="3 3" />
                      <Line type="monotone" dataKey="x" stroke={C.primary} strokeWidth={2} dot={{ r: 2 }} name="Cycle (s)" />
                    </LineChart>
                  </ChartBox>
                </Section>
              </Grid>
            </Grid>
          )}
        </>
      )}
    </Box>
  );
}

function Kpi({ label, value, color }: { label: string; value: React.ReactNode; color?: string }) {
  return (
    <Grid item xs={6} sm={4} md={2}>
      <Paper sx={{ p: 2 }}>
        <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</Typography>
        <Typography sx={{ fontFamily: MONO_STACK, fontWeight: 700, fontSize: 26, color: color || "text.primary", lineHeight: 1.2 }}>{value}</Typography>
      </Paper>
    </Grid>
  );
}

function ChartBox({ children }: { children: React.ReactElement }) {
  return (
    <Box sx={{ width: "100%", height: 280 }}>
      <ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer>
    </Box>
  );
}
