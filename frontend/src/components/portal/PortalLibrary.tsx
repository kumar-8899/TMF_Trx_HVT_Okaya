/** Portal → Library: the searchable set of PDFs (hardware manuals, wiring drawings…) users upload or an
 * app ships. Everyone with PORTAL.VIEW can search and read; PORTAL.UPLOAD adds/edits; PORTAL.MANAGE deletes.
 * Bundled (app-shipped) documents are read-only. */
import DeleteOutline from "@mui/icons-material/DeleteOutline";
import EditOutlined from "@mui/icons-material/EditOutlined";
import Search from "@mui/icons-material/Search";
import UploadFile from "@mui/icons-material/UploadFile";
import VisibilityOutlined from "@mui/icons-material/VisibilityOutlined";
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, InputAdornment,
  Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Tooltip, Typography,
} from "@mui/material";
import { useEffect, useRef, useState } from "react";

import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { PdfViewer, type ViewedDoc } from "./PdfViewer";

export interface LibDoc {
  id: string; title: string; filename: string; bytes: number; tags: string[]; description: string;
  uploaded_by: string | null; ts: number | null; source: "upload" | "bundled"; pages: number | null;
  searchable: boolean;
}
interface Hit { id: string; title: string; snippet: string }

const errText = (e: any) => e?.body?.detail ?? e?.message ?? "Something went wrong";
const kb = (n: number) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
const prettyTitle = (name: string) => name.replace(/\.pdf$/i, "").replace(/[_\s]+/g, " ").trim();

interface Draft { id?: string; file?: File; title: string; tags: string; description: string }

export function PortalLibrary() {
  const { can } = useAuth();
  const canUpload = can("PORTAL.UPLOAD");
  const canManage = can("PORTAL.MANAGE");

  const [docs, setDocs] = useState<LibDoc[]>([]);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [viewing, setViewing] = useState<ViewedDoc | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = () => api.get("/portal/library").then(setDocs).catch((e) => setError(errText(e)));
  useEffect(() => { refresh(); }, []);

  useEffect(() => {
    if (!q.trim()) { setHits(null); return; }
    const t = setTimeout(() => api.get(`/portal/library/search?q=${encodeURIComponent(q)}`)
      .then((r) => setHits(r.hits)).catch(() => setHits([])), 250);
    return () => clearTimeout(t);
  }, [q]);

  const view = (d: { id: string; title: string; filename?: string }) =>
    setViewing({ id: d.id, title: d.title, filename: d.filename ?? docs.find((x) => x.id === d.id)?.filename ?? "" });

  const pick = (f: File | undefined) => {
    if (fileInput.current) fileInput.current.value = "";
    if (f) setDraft({ file: f, title: prettyTitle(f.name), tags: "", description: "" });
  };

  const submit = async () => {
    if (!draft) return;
    setBusy(true); setError(null);
    try {
      if (draft.id) {
        await api.patch(`/portal/library/${draft.id}`, { title: draft.title, tags: draft.tags, description: draft.description });
        setNotice("Details saved.");
      } else if (draft.file) {
        const p = new URLSearchParams({ filename: draft.file.name, title: draft.title, tags: draft.tags, description: draft.description });
        await api.postRaw(`/portal/library?${p}`, draft.file, "application/pdf");
        setNotice(`Added “${draft.title}”.`);
      }
      setDraft(null);
      await refresh();
    } catch (e) {
      setError(errText(e));
    } finally { setBusy(false); }
  };

  const remove = async (d: LibDoc) => {
    if (!window.confirm(`Delete “${d.title}” from the library? This cannot be undone.`)) return;
    try { await api.del(`/portal/library/${d.id}`); setNotice(`Deleted “${d.title}”.`); await refresh(); }
    catch (e) { setError(errText(e)); }
  };

  return (
    <Box>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }} sx={{ mb: 2 }}>
        <TextField size="small" sx={{ flex: 1 }} placeholder="Search manuals and drawings (titles, tags, and the text inside PDFs)…"
          value={q} onChange={(e) => setQ(e.target.value)} inputProps={{ "aria-label": "search library" }}
          InputProps={{ startAdornment: <InputAdornment position="start"><Search fontSize="small" /></InputAdornment> }} />
        {canUpload && (
          <>
            <input ref={fileInput} type="file" accept="application/pdf,.pdf" hidden aria-label="choose a PDF"
              onChange={(e) => pick(e.target.files?.[0])} />
            <Button variant="contained" startIcon={<UploadFile />} onClick={() => fileInput.current?.click()}>Add PDF</Button>
          </>
        )}
      </Stack>

      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}

      {hits ? (
        <Paper variant="outlined">
          {hits.length === 0 ? <Typography sx={{ p: 2 }} color="text.secondary">No matches for “{q}”.</Typography> : hits.map((h) => (
            <Box key={h.id} onClick={() => view(h)} role="button" tabIndex={0}
              sx={{ p: 1.5, cursor: "pointer", borderBottom: "1px solid", borderColor: "divider", "&:hover": { bgcolor: "action.hover" } }}>
              <Typography sx={{ fontWeight: 700 }}>{h.title}</Typography>
              {h.snippet && <Typography variant="body2" color="text.secondary">{h.snippet}</Typography>}
            </Box>
          ))}
        </Paper>
      ) : docs.length === 0 ? (
        <Paper variant="outlined" sx={{ p: 3, textAlign: "center" }}>
          <Typography sx={{ fontWeight: 700 }}>No documents yet</Typography>
          <Typography variant="body2" color="text.secondary">
            {canUpload ? "Use “Add PDF” to upload an instrument manual or a wiring drawing." : "Ask an engineer or admin to add the hardware manuals for this station."}
          </Typography>
        </Paper>
      ) : (
        <Paper variant="outlined" sx={{ overflowX: "auto" }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 700 }}>Document</TableCell><TableCell sx={{ fontWeight: 700 }}>Pages</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Size</TableCell><TableCell sx={{ fontWeight: 700 }}>Added</TableCell>
                <TableCell align="right" sx={{ fontWeight: 700 }}>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {docs.map((d) => (
                <TableRow key={d.id} hover>
                  <TableCell>
                    <Typography sx={{ fontWeight: 600 }}>{d.title}</Typography>
                    {d.description && <Typography variant="caption" color="text.secondary" component="div">{d.description}</Typography>}
                    <Stack direction="row" gap={0.5} flexWrap="wrap" sx={{ mt: 0.5 }}>
                      {d.source === "bundled" && <Chip size="small" color="info" label="shipped with the app" />}
                      {d.tags.filter((t) => t !== "bundled").map((t) => <Chip key={t} size="small" variant="outlined" label={t} />)}
                      {!d.searchable && (
                        <Tooltip title="No text layer was found (a scan?). You can still open it, but its contents can't be searched.">
                          <Chip size="small" variant="outlined" color="warning" label="not searchable" />
                        </Tooltip>
                      )}
                    </Stack>
                  </TableCell>
                  <TableCell>{d.pages ?? "—"}</TableCell>
                  <TableCell>{kb(d.bytes)}</TableCell>
                  <TableCell>
                    {d.source === "bundled" ? "—" : `${d.ts ? new Date(d.ts * 1000).toLocaleDateString() : ""}${d.uploaded_by ? ` · ${d.uploaded_by}` : ""}`}
                  </TableCell>
                  <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                    <Tooltip title="Open"><IconButton size="small" aria-label={`open ${d.title}`} onClick={() => view(d)}><VisibilityOutlined fontSize="small" /></IconButton></Tooltip>
                    {canUpload && d.source === "upload" && (
                      <Tooltip title="Edit details"><IconButton size="small" aria-label={`edit ${d.title}`}
                        onClick={() => setDraft({ id: d.id, title: d.title, tags: d.tags.join(", "), description: d.description })}><EditOutlined fontSize="small" /></IconButton></Tooltip>
                    )}
                    {canManage && d.source === "upload" && (
                      <Tooltip title="Delete"><IconButton size="small" aria-label={`delete ${d.title}`} onClick={() => remove(d)}><DeleteOutline fontSize="small" /></IconButton></Tooltip>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}

      <Dialog open={Boolean(draft)} onClose={() => !busy && setDraft(null)} fullWidth maxWidth="sm">
        <DialogTitle>{draft?.id ? "Edit document details" : "Add a PDF to the library"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {draft?.file && <Typography variant="body2" color="text.secondary">{draft.file.name} · {kb(draft.file.size)}</Typography>}
            <TextField label="Title" size="small" value={draft?.title ?? ""} onChange={(e) => setDraft((d) => d && { ...d, title: e.target.value })} />
            <TextField label="Tags (comma separated)" size="small" helperText="e.g. tenma, power supply, wiring"
              value={draft?.tags ?? ""} onChange={(e) => setDraft((d) => d && { ...d, tags: e.target.value })} />
            <TextField label="Description" size="small" multiline minRows={2} value={draft?.description ?? ""}
              onChange={(e) => setDraft((d) => d && { ...d, description: e.target.value })} />
            {error && <Alert severity="error">{error}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDraft(null)} disabled={busy}>Cancel</Button>
          <Button variant="contained" onClick={submit} disabled={busy || !draft?.title.trim()}>{draft?.id ? "Save" : "Upload"}</Button>
        </DialogActions>
      </Dialog>

      <PdfViewer doc={viewing} onClose={() => setViewing(null)} />
    </Box>
  );
}
