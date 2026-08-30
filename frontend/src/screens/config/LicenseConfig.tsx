import { Alert, Box, Button, Stack, TextField, Typography } from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { Section, StatusChip } from "../../components/ui";
import { MONO_STACK } from "../../theme/theme";

/** Settings → License — Keystation licensing status + activation (secure
 * distribution P1). Two flows: online-issued or air-gapped (.ksreq → mint on the
 * issuer → install .kslease). With the stub provider this collapses to a status line. */
export function LicenseConfig() {
  const [st, setSt] = useState<any | null>(null);
  const [leasePath, setLeasePath] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => api.get("/license/status").then(setSt).catch((e) => setError(e.message));
  useEffect(() => { refresh(); }, []);

  const exportRequest = async () => {
    setError(null); setMsg(null);
    try {
      const req = await api.post("/license/request", {});
      const blob = new Blob([JSON.stringify(req, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "activation-request.ksreq";
      a.click();
      URL.revokeObjectURL(a.href);
      setMsg("Activation request exported — mint a lease on the issuer, then install it below.");
    } catch (e: any) { setError(e.message); }
  };

  const install = async () => {
    setError(null); setMsg(null);
    try {
      const r = await api.post("/license/activate", { bundle_path: leasePath });
      setMsg(r.note || "Lease installed.");
      refresh();
    } catch (e: any) { setError(e.message); }
  };

  const licensed = !!st?.licensed;
  const keystation = st?.provider === "keystation";

  return (
    <Section title="License" subtitle="Keystation activation & entitlements">
      {error && <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setError(null)}>{error}</Alert>}
      {msg && <Alert severity="success" sx={{ mb: 1.5 }} onClose={() => setMsg(null)}>{msg}</Alert>}

      <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
        <Box>
          <Typography variant="caption" color="text.secondary" display="block">PROVIDER</Typography>
          <Typography sx={{ fontFamily: MONO_STACK }}>{st?.provider ?? "—"}</Typography>
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary" display="block">PRODUCT</Typography>
          <Typography sx={{ fontFamily: MONO_STACK }}>{st?.product ?? "—"}</Typography>
        </Box>
        {keystation && (
          <>
            <Box>
              <Typography variant="caption" color="text.secondary" display="block">STATE</Typography>
              <StatusChip label={st?.state ?? "—"} kind={licensed ? "pass" : "fail"} />
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" display="block">BOOTSTRAP</Typography>
              <Typography sx={{ fontFamily: MONO_STACK }}>{st?.bootstrap ?? "—"}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" display="block">KEY TIER</Typography>
              <Typography sx={{ fontFamily: MONO_STACK }}>{st?.key_tier ?? "—"}</Typography>
            </Box>
            {st?.tripwire_fired && <StatusChip label="tripwire" kind="fail" />}
            <Box>
              <Typography variant="caption" color="text.secondary" display="block">AMC (updates)</Typography>
              {(() => {
                const amc = st?.amc;
                if (!amc) return <Typography variant="body2" color="text.secondary">none — updates require an AMC</Typography>;
                const end = new Date(amc.expires * 1000);
                const active = amc.expires * 1000 >= Date.now();
                return (
                  <Typography variant="body2">
                    {active ? "valid until " : "expired on "}<b>{end.toLocaleDateString()}</b>
                    {!active && <Typography component="span" variant="caption" color="text.secondary"> — software continues to run normally</Typography>}
                  </Typography>
                );
              })()}
            </Box>
          </>
        )}
        {!keystation && st?.detail && (
          <Typography variant="body2" color="text.secondary">{st.detail}</Typography>
        )}
      </Stack>

      {keystation && (
        <>
          {!licensed && (
            <Alert severity="warning" sx={{ mb: 1.5, py: 0 }}>
              Station is not licensed — premium modules stay off until a lease is installed.
            </Alert>
          )}
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Button variant="outlined" onClick={exportRequest}>Export activation request (.ksreq)</Button>
            <TextField size="small" label=".kslease path on station" value={leasePath}
              onChange={(e) => setLeasePath(e.target.value)} sx={{ minWidth: 320 }} />
            <Button variant="contained" disabled={!leasePath} onClick={install}>Install lease</Button>
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
            Air-gapped flow: export the request → mint a lease on the Keystation issuer → copy the
            .kslease to this station and install. A restart re-runs the module gate.
          </Typography>
        </>
      )}
    </Section>
  );
}
