/** App identity / branding (super_admin). Rebrands the app for a project without
 * editing app.json — persisted as a DB override that /branding merges live. TEMPLATE.md
 * §1: an application rebrands via config, never code edits. */
import { Alert, Box, Button, Stack, TextField, Typography } from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { resetBranding } from "../../hooks/useBranding";
import { PageHeader, Section } from "../../components/ui";

interface Brand { name: string; short: string; product: string; tagline: string; version?: string }
const BLANK: Brand = { name: "", short: "", product: "", tagline: "" };

export function ConfigBranding({ embedded = false }: { embedded?: boolean }) {
  const [b, setB] = useState<Brand>(BLANK);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => { api.get("/branding").then((x) => setB({ ...BLANK, ...x })).catch((e) => setError(e.message)); }, []);
  const set = (k: keyof Brand, v: string) => setB((d) => ({ ...d, [k]: v }));

  const save = async () => {
    setBusy(true); setError(null); setNotice(null);
    try {
      const out = await api.put("/branding", {
        name: b.name, short: b.short, product: b.product, tagline: b.tagline,
      });
      setB({ ...BLANK, ...out });
      resetBranding();                       // clears the session cache
      document.title = out.product || out.name;
      setNotice("Saved. Reload to apply everywhere (title bar, login, header).");
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Box>
      {!embedded && <PageHeader title="App identity" subtitle="Rebrand the app for this project — applied live, no restart" />}
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}

      <Section title="Identity" subtitle="Shown on the login page, the header, and the browser tab">
        <Stack spacing={2}>
          <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
            <Box sx={{
              width: 40, height: 40, borderRadius: 2, flexShrink: 0,
              background: (t) => `linear-gradient(135deg, ${t.palette.primary.light}, ${t.palette.primary.dark})`,
              display: "flex", alignItems: "center", justifyContent: "center",
              color: (t) => t.palette.primary.contrastText, fontWeight: 800, fontSize: 20,
            }}>{b.short || "?"}</Box>
            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{b.name || "—"}</Typography>
              <Typography variant="caption" color="text.secondary">{b.product || "—"}</Typography>
            </Box>
          </Stack>
          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
            <TextField label="Name" value={b.name} sx={{ width: 260 }} onChange={(e) => set("name", e.target.value)}
              helperText="Displayed app name (e.g. Acme EOL Tester)" inputProps={{ "aria-label": "brand_name" }} />
            <TextField label="Badge" value={b.short} sx={{ width: 100 }} onChange={(e) => set("short", e.target.value.slice(0, 2))}
              helperText="1–2 chars" inputProps={{ "aria-label": "brand_short", maxLength: 2 }} />
          </Stack>
          <TextField label="Product / tab title" value={b.product} onChange={(e) => set("product", e.target.value)}
            fullWidth helperText="Browser tab + login subtitle" inputProps={{ "aria-label": "brand_product" }} />
          <TextField label="Tagline" value={b.tagline} onChange={(e) => set("tagline", e.target.value)}
            fullWidth helperText="Login-page notice line" inputProps={{ "aria-label": "brand_tagline" }} />
          <Box>
            <Button variant="contained" onClick={save} disabled={busy || !b.name}>Save identity</Button>
          </Box>
        </Stack>
      </Section>
    </Box>
  );
}
