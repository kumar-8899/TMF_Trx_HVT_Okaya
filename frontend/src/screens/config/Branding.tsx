/** App identity / branding (super_admin). Rebrands the app for a project without
 * editing app.json — persisted as a DB override that /branding merges live. TEMPLATE.md
 * §1: an application rebrands via config, never code edits. */
import { Alert, Box, Button, Stack, TextField, Typography } from "@mui/material";
import { useEffect, useRef, useState } from "react";

import { api } from "../../api/client";
import { resetBranding } from "../../hooks/useBranding";
import { PageHeader, Section } from "../../components/ui";

interface Brand {
  name: string; short: string; product: string; tagline: string; version?: string;
  logo_client?: string; logo_exeliq?: string;
}
const BLANK: Brand = { name: "", short: "", product: "", tagline: "", logo_client: "", logo_exeliq: "" };

const MAX_LOGO = 512 * 1024;   // 512 KB — logos are small; keep the branding record light

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
        logo_client: b.logo_client || "", logo_exeliq: b.logo_exeliq || "",
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

      <Section title="Logos" subtitle="Client logo shows top-left, Exeliq logo top-right (PNG or SVG, ≤ 512 KB)">
        <Stack direction="row" spacing={4} flexWrap="wrap" useFlexGap>
          <LogoField label="Client logo" value={b.logo_client} onChange={(v) => set("logo_client", v)} onError={setError} />
          <LogoField label="Exeliq logo" value={b.logo_exeliq} onChange={(v) => set("logo_exeliq", v)} onError={setError} />
        </Stack>
        <Box sx={{ mt: 2 }}>
          <Button variant="contained" onClick={save} disabled={busy || !b.name}>Save logos</Button>
        </Box>
      </Section>
    </Box>
  );
}

function LogoField({ label, value, onChange, onError }: {
  label: string; value?: string; onChange: (v: string) => void; onError: (m: string) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const pick = (file: File) => {
    if (file.size > MAX_LOGO) { onError(`${label} too large (max 512 KB)`); return; }
    const reader = new FileReader();
    reader.onload = () => onChange(String(reader.result || ""));
    reader.readAsDataURL(file);          // stored + served as a data: URL
  };
  return (
    <Box sx={{ width: 280 }}>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>{label}</Typography>
      <Box sx={{
        height: 72, borderRadius: 2, border: "1px dashed", borderColor: "divider", mb: 1,
        display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden",
        bgcolor: "action.hover",
      }}>
        {value ? <Box component="img" src={value} alt={label} sx={{ maxHeight: 64, maxWidth: 260, objectFit: "contain" }} />
               : <Typography variant="caption" color="text.disabled">No logo</Typography>}
      </Box>
      <Stack direction="row" spacing={1}>
        <Button size="small" variant="outlined" onClick={() => ref.current?.click()}>Choose file…</Button>
        {value && <Button size="small" color="inherit" onClick={() => onChange("")}>Clear</Button>}
      </Stack>
      <input ref={ref} type="file" accept="image/png,image/jpeg,image/svg+xml" hidden
        onChange={(e) => { const f = e.target.files?.[0]; if (f) pick(f); e.target.value = ""; }} />
    </Box>
  );
}
