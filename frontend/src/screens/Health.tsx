import { CheckCircle, Cancel, HelpOutline, PlayArrow, RemoveCircleOutline, Replay } from "@mui/icons-material";
import {
  Alert, Box, Button, Chip, Collapse, Divider, MenuItem, Paper, Stack, Table, TableBody,
  TableCell, TableHead, TableRow, TextField, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageHeader, Section } from "../components/ui";
import { useStream } from "../hooks/useStream";
import { MONO_STACK } from "../theme/theme";

interface Verdict {
  check_id: string; status: string; summary?: string; elapsed_ms?: number;
  instance_id?: string | null; data?: Record<string, any>; error?: any; signature?: any;
}
interface Suggestion { check_id: string; matched: boolean; summary?: string; remedy?: { text?: string } | null; references?: string[] }
interface Run { health_run_id: string; overall: string; counts: Record<string, number>; verdicts: Verdict[]; suggestions: Suggestion[]; summary: string; ts: number }
interface CheckMeta {
  id: string; title: string; group: string; severity: string; purpose?: string;
  impact?: string; user_action?: string[]; disruptive?: boolean; reachable?: boolean;
}

// overall verdict -> the question operators actually ask: "can I start production?"
const READINESS: Record<string, { label: string; color: string; bg: string }> = {
  healthy: { label: "✓ Production Ready", color: "#1A6B3C", bg: "#E6F4EC" },
  degraded: { label: "⚠ Ready with Warnings", color: "#8A6100", bg: "#FBF1DA" },
  unhealthy: { label: "✖ Production Blocked", color: "#9B1C1C", bg: "#FBE9E9" },
  incomplete: { label: "⚠ Readiness Unknown", color: "#8A6100", bg: "#FBF1DA" },
};
// business-function ordering (HEALTH UX §7) — not the technical domains
const GROUP_ORDER = ["Core Software", "Production Systems", "Test Equipment", "External Systems", "System"];
const BAD = new Set(["fail", "timeout", "error"]);
const GOOD = new Set(["pass"]);

type Level = "operator" | "technician" | "engineer";

function StatusGlyph({ status }: { status: string }) {
  if (GOOD.has(status)) return <CheckCircle fontSize="small" sx={{ color: "status.pass" }} />;
  if (BAD.has(status)) return <Cancel fontSize="small" sx={{ color: "status.fail" }} />;
  if (status === "pending") return <RemoveCircleOutline fontSize="small" sx={{ color: "text.disabled" }} />;
  return <HelpOutline fontSize="small" sx={{ color: "status.idle" }} />;  // unavailable/skipped
}

export function Health() {
  const { can } = useAuth();
  const [checks, setChecks] = useState<CheckMeta[]>([]);
  const [suites, setSuites] = useState<any[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [current, setCurrent] = useState<Run | null>(null);
  const [selected, setSelected] = useState<Run | null>(null);
  const [suite, setSuite] = useState("smoke");
  const [activeRun, setActiveRun] = useState<string | null>(null);
  const [live, setLive] = useState<Record<string, string>>({});
  const [level, setLevel] = useState<Level>("operator");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.get("/health/runs").then((r) => setRuns([...r].reverse())).catch((e) => setError(e.message));
    api.get("/health/current").then(setCurrent).catch(() => {});
  }, []);
  useEffect(() => {
    api.get("/health/checks").then(setChecks).catch((e) => setError(e.message));
    api.get("/health/suites").then(setSuites).catch(() => {});
    refresh();
  }, [refresh]);

  const { last } = useStream<any>(activeRun ? `/health/run/${activeRun}/stream` : null);
  useEffect(() => {
    if (!last) return;
    if (last.type === "check-completed") setLive((p) => ({ ...p, [last.check_id]: last.status }));
    if (last.type === "health-run-finished") {
      api.get(`/health/runs/${activeRun}`).then((r) => { setSelected(r); setCurrent(r); }).catch(() => {});
      setActiveRun(null); refresh();
    }
  }, [last]); // eslint-disable-line react-hooks/exhaustive-deps

  const runSuite = async () => {
    setError(null); setLive({}); setSelected(null);
    try { setActiveRun((await api.post("/health/run", { suite })).health_run_id); }
    catch (e: any) { setError(e.message); }
  };
  const runCheck = async (id: string) => {
    setError(null); setLive({});
    try { setActiveRun((await api.post(`/health/checks/${id}/run`, {})).health_run_id); }
    catch (e: any) { setError(e.message); }
  };

  const metaById = useMemo(() => Object.fromEntries(checks.map((c) => [c.id, c])), [checks]);
  const view = selected ?? current;
  const suggById = useMemo(
    () => Object.fromEntries((view?.suggestions ?? []).map((s) => [s.check_id, s])),
    [view],
  );

  // Rows to render: a finished/live run's verdicts, else the check list as "pending".
  const rows: Verdict[] = useMemo(() => {
    if (view?.verdicts?.length && !activeRun) return view.verdicts;
    return checks.map((c) => ({ check_id: c.id, status: live[c.id] || "pending", summary: "" }));
  }, [view, activeRun, checks, live]);

  // group by business function
  const grouped = useMemo(() => {
    const g: Record<string, Verdict[]> = {};
    for (const r of rows) {
      const grp = metaById[r.check_id]?.group || "System";
      (g[grp] ||= []).push(r);
    }
    return GROUP_ORDER.filter((k) => g[k]?.length).map((k) => [k, g[k]] as const)
      .concat(Object.keys(g).filter((k) => !GROUP_ORDER.includes(k)).map((k) => [k, g[k]] as const));
  }, [rows, metaById]);

  const readiness = view ? (READINESS[view.overall] ?? READINESS.incomplete) : null;

  return (
    <Box>
      <PageHeader
        title="Production Readiness"
        subtitle="Can I start production? — system health at a glance"
        actions={can("HEALTH.RUN") && (
          <Stack direction="row" spacing={1}>
            <TextField select size="small" label="Suite" value={suite} onChange={(e) => setSuite(e.target.value)} sx={{ width: 130 }}>
              {suites.map((s) => <MenuItem key={s.name} value={s.name}>{s.name}</MenuItem>)}
            </TextField>
            <Button variant="contained" startIcon={<PlayArrow />} disabled={Boolean(activeRun)} onClick={runSuite}>
              {activeRun ? "Running…" : "Re-test"}
            </Button>
          </Stack>
        )}
      />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {/* readiness verdict banner */}
      {readiness && (
        <Paper sx={{ p: 2.5, mb: 2, bgcolor: readiness.bg, borderLeft: `6px solid ${readiness.color}` }}>
          <Typography variant="h5" sx={{ color: readiness.color, fontWeight: 700 }}>{readiness.label}</Typography>
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            {Object.entries(view!.counts).map(([k, n]) => <Chip key={k} size="small" label={`${k}: ${n}`} />)}
          </Stack>
        </Paper>
      )}

      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }} flexWrap="wrap" useFlexGap>
        <ToggleButtonGroup size="small" exclusive value={level} onChange={(_, v) => v && setLevel(v)}>
          <ToggleButton value="operator">Operator</ToggleButton>
          <ToggleButton value="technician">Technician</ToggleButton>
          <ToggleButton value="engineer">Engineer</ToggleButton>
        </ToggleButtonGroup>
        {selected && <Button size="small" onClick={() => setSelected(null)}>Back to latest</Button>}
      </Stack>

      <Stack direction={{ xs: "column", lg: "row" }} spacing={2}>
        <Box sx={{ flex: 2, minWidth: 0 }}>
          {rows.length === 0 ? <EmptyState message="No checks. Press Re-test." /> : grouped.map(([grp, items]) => (
            <Section key={grp} title={grp} sx={{ mb: 2 }}>
              <Stack divider={<Divider flexItem />} spacing={0}>
                {items.map((v) => {
                  const meta = metaById[v.check_id] || ({ title: v.check_id } as CheckMeta);
                  const st = activeRun ? (live[v.check_id] || "pending") : v.status;
                  const bad = BAD.has(st);
                  const sugg = suggById[v.check_id];
                  return (
                    <Box key={v.check_id} sx={{ py: 1 }}>
                      <Stack direction="row" alignItems="center" spacing={1}>
                        <StatusGlyph status={st} />
                        <Typography variant="subtitle2" sx={{ flex: 1 }}>{meta.title}</Typography>
                        {meta.severity === "critical" && bad && <Chip size="small" color="error" label="critical" sx={{ height: 18 }} />}
                        <Typography variant="caption" sx={{ color: "text.secondary", textTransform: "uppercase" }}>{st}</Typography>
                        {can("HEALTH.RUN") && <Button size="small" startIcon={<Replay />} disabled={Boolean(activeRun)} onClick={() => runCheck(v.check_id)}>Re-test</Button>}
                      </Stack>

                      {/* OPERATOR: impact + what to do + known-issue remedy (only when bad) */}
                      <Collapse in={bad} unmountOnExit>
                        <Box sx={{ ml: 4, mt: 0.5 }}>
                          {meta.impact && <Typography variant="body2"><b>Impact:</b> {meta.impact}</Typography>}
                          {(meta.user_action?.length ?? 0) > 0 && (
                            <Box sx={{ mt: 0.5 }}>
                              <Typography variant="body2"><b>What to do:</b></Typography>
                              <ol style={{ margin: "2px 0 0 18px" }}>
                                {meta.user_action!.map((a, i) => <li key={i}><Typography variant="body2">{a}</Typography></li>)}
                              </ol>
                            </Box>
                          )}
                          {sugg?.matched && (
                            <Alert severity="warning" sx={{ mt: 1, py: 0 }}>
                              <Typography variant="body2"><b>Known issue:</b> {sugg.summary}</Typography>
                              {sugg.remedy?.text && <Typography variant="body2">{sugg.remedy.text}</Typography>}
                            </Alert>
                          )}
                        </Box>
                      </Collapse>

                      {/* TECHNICIAN: diagnostic summary + key/value data */}
                      {level !== "operator" && (st !== "pending") && (
                        <Box sx={{ ml: 4, mt: 0.5 }}>
                          {v.summary && <Typography variant="body2" sx={{ color: "text.secondary" }}>{v.summary}</Typography>}
                          {v.data && Object.keys(v.data).length > 0 && (
                            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
                              {Object.entries(v.data).map(([k, val]) =>
                                <Chip key={k} size="small" variant="outlined" label={`${k}: ${JSON.stringify(val)}`} sx={{ fontFamily: MONO_STACK }} />)}
                            </Stack>
                          )}
                        </Box>
                      )}

                      {/* ENGINEER: ids, timing, signature, raw error */}
                      {level === "engineer" && (st !== "pending") && (
                        <Box sx={{ ml: 4, mt: 0.5, fontFamily: MONO_STACK, fontSize: 12, color: "text.secondary" }}>
                          <div>check_id: {v.check_id}</div>
                          {v.elapsed_ms != null && <div>duration: {v.elapsed_ms} ms</div>}
                          {v.signature && <div>signature: {JSON.stringify(v.signature)}</div>}
                          {v.error && <div>error: {JSON.stringify(v.error)}</div>}
                        </Box>
                      )}
                    </Box>
                  );
                })}
              </Stack>
            </Section>
          ))}
        </Box>

        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Section title="History" bodyPad={0}>
            {runs.length === 0 ? <EmptyState message="No runs." /> : (
              <Table size="small">
                <TableHead><TableRow><TableCell>Result</TableCell><TableCell>When</TableCell></TableRow></TableHead>
                <TableBody>
                  {runs.slice(0, 15).map((r) => {
                    const rd = READINESS[r.overall] ?? READINESS.incomplete;
                    return (
                      <TableRow key={r.health_run_id} hover sx={{ cursor: "pointer" }} onClick={() => setSelected(r)}>
                        <TableCell><Typography variant="caption" sx={{ color: rd.color, fontWeight: 600 }}>{rd.label}</Typography></TableCell>
                        <TableCell sx={{ color: "text.secondary" }}>{new Date(r.ts * 1000).toLocaleString()}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </Section>
        </Box>
      </Stack>
    </Box>
  );
}
