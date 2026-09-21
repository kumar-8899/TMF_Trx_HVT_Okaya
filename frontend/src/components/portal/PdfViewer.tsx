/** Full-screen PDF viewer for a library document.
 *
 * The PDF is fetched WITH the bearer header (an <iframe src> can't send one), turned into a `blob:` URL
 * and shown in an <iframe>: the browser's / WebView2's own PDF viewer then provides page navigation,
 * zoom, search, thumbnails and print — verified in a real pywebview/WebView2 window (no pdf.js needed).
 * "Save a copy" goes through the backend (`?save=true`) because a blob download is invisible in the
 * native window; it writes to the PC's Downloads folder and reports the path. */
import Close from "@mui/icons-material/Close";
import Download from "@mui/icons-material/Download";
import {
  Alert, Box, Button, CircularProgress, Dialog, DialogTitle, IconButton, Stack, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../../api/client";

export interface ViewedDoc { id: string; title: string; filename: string }

export function PdfViewer({ doc, onClose }: { doc: ViewedDoc | null; onClose: () => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    if (!doc) return;
    let alive = true;
    let made: string | null = null;
    setUrl(null); setError(null); setSaved(null);
    api.getBlob(`/portal/library/${encodeURIComponent(doc.id)}/file`)
      .then((b) => {
        if (!alive) return;
        made = URL.createObjectURL(new Blob([b], { type: "application/pdf" }));
        setUrl(made);
      })
      .catch((e) => alive && setError(e?.body?.detail ?? e?.message ?? "Could not load the document"));
    return () => { alive = false; if (made) URL.revokeObjectURL(made); };
  }, [doc?.id]);

  const save = () => {
    if (!doc) return;
    api.get(`/portal/library/${encodeURIComponent(doc.id)}/file?save=true`)
      .then((r) => setSaved(r.path))
      .catch((e) => setError(e?.body?.detail ?? e?.message ?? "Could not save a copy"));
  };

  return (
    <Dialog open={Boolean(doc)} onClose={onClose} fullWidth maxWidth="xl"
      PaperProps={{ sx: { height: "92vh" } }}>
      <DialogTitle sx={{ display: "flex", alignItems: "center", gap: 1, py: 1 }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle1" noWrap sx={{ fontWeight: 700 }}>{doc?.title}</Typography>
          <Typography variant="caption" color="text.secondary" noWrap>{doc?.filename}</Typography>
        </Box>
        <Button size="small" startIcon={<Download />} onClick={save} disabled={!url}>Save a copy</Button>
        <IconButton aria-label="close viewer" onClick={onClose}><Close /></IconButton>
      </DialogTitle>
      {saved && <Alert severity="success" sx={{ mx: 2 }} onClose={() => setSaved(null)}>Saved to <code>{saved}</code></Alert>}
      {error && <Alert severity="error" sx={{ mx: 2 }}>{error}</Alert>}
      <Box sx={{ flex: 1, minHeight: 0, p: 1 }}>
        {url ? (
          <iframe title={doc ? `PDF: ${doc.title}` : "PDF"} src={url}
            style={{ width: "100%", height: "100%", border: 0, borderRadius: 4 }} />
        ) : !error && (
          <Stack alignItems="center" justifyContent="center" sx={{ height: "100%" }}><CircularProgress /></Stack>
        )}
      </Box>
    </Dialog>
  );
}
