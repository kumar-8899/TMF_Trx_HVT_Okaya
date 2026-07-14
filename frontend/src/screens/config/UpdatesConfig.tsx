import { Alert, Box, Button, Chip, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography } from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { Section, StatusChip } from "../../components/ui";
import { MONO_STACK } from "../../theme/theme";

/** Settings → Updates — signed code updates (secure distribution P3). Ingest a
 * .ksupdate bundle (verified through the licensing core), see the applicability
 * verdict (publish ≠ deploy), and operator-gate the apply. The physical artifact
 * swap happens at the next launcher restart. */
export function UpdatesConfig() {
  const [current, setCurrent] = useState<any>(null);
  const [offers, setOffers] = useState<any[]>([]);
  const [source, setSource] = useState<string | null>(null);
  const [path, setPath] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  const refresh = () => api.get("/update/offers")
    .then((r) => { setCurrent(r.current); setOffers(r.offers || []); setSource(r.source || null); })
    .catch((e) => setError(e.message));
  useEffect(() => { refresh(); }, []);

  const checkGithub = async () => {
    setChecking(true); setError(null); setMsg(null);
    try {
      const r = await api.post("/update/check", {});
      setMsg(`Pulled ${r.release} from ${r.source} — ${r.version} ${r.verdict?.applicable ? "applicable" : "not applicable"}`);
      refresh();
    } catch (e: any) { setError(e.message); } finally { setChecking(false); }
  };

  const ingest = async () => {
    setError(null); setMsg(null);
    try {
      const r = await api.post("/update/ingest", { bundle_path: path });
      setMsg(`Ingested ${r.track} ${r.version} — ${r.verdict?.applicable ? "applicable" : "not applicable"}: ${r.verdict?.reason}`);
      refresh();
    } catch (e: any) { setError(e.message); }
  };

  const apply = async (id: string) => {
    setError(null); setMsg(null);
    try {
      const r = await api.post(`/update/apply/${id}`, {});
      setMsg(r.note || "Apply staged.");
      refresh();
    } catch (e: any) { setError(e.message); }
  };

  return (
    <Section title="Updates" subtitle="signed code updates (Keystation)">
      {error && <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setError(null)}>{error}</Alert>}
      {msg && <Alert severity="info" sx={{ mb: 1.5 }} onClose={() => setMsg(null)}>{msg}</Alert>}

      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Installed framework: <b style={{ fontFamily: MONO_STACK }}>{current?.version ?? "—"}</b>
        {current?.abi >= 0 && <> · core ABI {current.abi}</>}
      </Typography>

      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
        <Button variant="contained" disabled={!source || checking} onClick={checkGithub}>
          {checking ? "Checking…" : "Check for updates"}
        </Button>
        {source && <Typography variant="caption" color="text.secondary">source: {source}</Typography>}
        <Box sx={{ width: 16 }} />
        <TextField size="small" label="or .ksupdate path on station" value={path}
          onChange={(e) => setPath(e.target.value)} sx={{ minWidth: 300 }} />
        <Button variant="outlined" disabled={!path} onClick={ingest}>Ingest file</Button>
      </Stack>

      {offers.length === 0 ? (
        <Typography variant="body2" color="text.secondary">No updates offered.</Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Track</TableCell><TableCell>Version</TableCell><TableCell>Trust</TableCell>
              <TableCell>Verdict</TableCell><TableCell>Status</TableCell><TableCell align="right">Action</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {offers.map((o) => (
              <TableRow key={o.release_id}>
                <TableCell>{o.track}</TableCell>
                <TableCell sx={{ fontFamily: MONO_STACK }}>{o.version}{o.criticality ? ` · ${o.criticality}` : ""}</TableCell>
                <TableCell>{o.verified
                  ? <Chip size="small" color="success" label="signed" />
                  : <Chip size="small" color="warning" label="unverified" />}</TableCell>
                <TableCell>
                  <StatusChip label={o.verdict?.applicable ? "applicable" : "no"} kind={o.verdict?.applicable ? "pass" : "idle"} />
                  <Typography variant="caption" color="text.secondary" display="block">{o.verdict?.reason}</Typography>
                </TableCell>
                <TableCell>{o.status}</TableCell>
                <TableCell align="right">
                  <Button size="small" variant="outlined"
                    disabled={!o.verdict?.applicable || o.status === "apply_pending"}
                    onClick={() => apply(o.release_id)}>
                    {o.status === "apply_pending" ? "pending restart" : "Apply"}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <Typography variant="caption" color="text.secondary" sx={{ mt: 1.5, display: "block" }}>
        Applying stages the release; the launcher swaps the artifact / core DLL on the next
        restart (a running binary can't replace itself). Core-ABI and pin mode are honored there.
      </Typography>
    </Section>
  );
}
