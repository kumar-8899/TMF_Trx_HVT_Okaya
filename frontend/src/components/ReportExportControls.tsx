import { ArrowDropDown, Download } from "@mui/icons-material";
import {
  Button, Checkbox, FormControlLabel, FormGroup, MenuItem, Popover, Stack, TextField, Tooltip, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../api/client";

interface Catalog {
  formats: { id: string; label: string; ext: string }[];
  fields: { id: string; label: string }[];
}

const STORE_KEY = "tmf.reportExport";

// Per-viewer convenience only — storage can be blocked (private window / pywebview), so never rely on it.
function loadPrefs(): { format?: string; fields?: string[] } {
  try { return JSON.parse(localStorage.getItem(STORE_KEY) || "{}"); } catch { return {}; }
}
function savePrefs(p: { format: string; fields: string[] }) {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(p)); } catch { /* ignore */ }
}

/** Format dropdown + "which parameters per test" checkboxes + Export, for the bulk (filtered) report export.
 * Everything comes from GET /reports/export/formats, so a new backend format/field appears with no UI change. */
export function ReportExportControls({ query, onExport }: { query: string; onExport: (path: string) => void }) {
  const [cat, setCat] = useState<Catalog | null>(null);
  const [format, setFormat] = useState("");
  const [fields, setFields] = useState<string[]>([]);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);

  useEffect(() => {
    let live = true;
    api.get("/reports/export/formats").then((c: Catalog) => {
      if (!live || !c?.formats?.length) return;
      const p = loadPrefs();
      const all = c.fields.map((f) => f.id);
      setCat(c);
      setFormat(c.formats.some((f) => f.id === p.format) ? (p.format as string) : c.formats[0].id);
      const keep = (p.fields ?? []).filter((f) => all.includes(f));
      setFields(keep.length ? keep : all);
    }).catch(() => { /* export stays hidden if the catalog can't load */ });
    return () => { live = false; };
  }, []);

  if (!cat) return null;

  const toggle = (id: string) => {
    const next = fields.includes(id) ? fields.filter((f) => f !== id) : [...fields, id];
    setFields(next);
    savePrefs({ format, fields: next });
  };
  const pickFormat = (f: string) => { setFormat(f); savePrefs({ format: f, fields }); };
  const none = fields.length === 0;
  const go = () => {
    const q = new URLSearchParams(query);
    q.set("format", format);
    q.set("fields", cat.fields.map((f) => f.id).filter((id) => fields.includes(id)).join(","));
    onExport(`/reports/full/export?${q.toString()}`);
  };

  return (
    <Stack direction="row" spacing={1} alignItems="center">
      <TextField select size="small" label="Format" value={format} sx={{ minWidth: 150 }}
        onChange={(e) => pickFormat(e.target.value)} inputProps={{ "aria-label": "Export format" }}>
        {cat.formats.map((f) => <MenuItem key={f.id} value={f.id}>{f.label}</MenuItem>)}
      </TextField>
      <Button size="small" variant="outlined" endIcon={<ArrowDropDown />} onClick={(e) => setAnchor(e.currentTarget)}>
        Test columns ({fields.length}/{cat.fields.length})
      </Button>
      <Popover open={Boolean(anchor)} anchorEl={anchor} onClose={() => setAnchor(null)}>
        <FormGroup sx={{ p: 2 }}>
          <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5 }}>
            Columns shown under every test
          </Typography>
          {cat.fields.map((f) => (
            <FormControlLabel key={f.id} label={f.label}
              control={<Checkbox size="small" checked={fields.includes(f.id)} onChange={() => toggle(f.id)} />} />
          ))}
        </FormGroup>
      </Popover>
      <Tooltip title={none ? "Tick at least one test column" : ""}>
        <span>
          <Button size="small" variant="contained" startIcon={<Download />} disabled={none} onClick={go}>
            Export (all filtered)
          </Button>
        </span>
      </Tooltip>
    </Stack>
  );
}
