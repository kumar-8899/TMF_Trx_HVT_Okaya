/** Context-aware help slide-over. Opens to the doc for the current screen, with
 * search and a link to the full /help page. (DEBUG/Help module.) */
import { Close, OpenInFull, Search } from "@mui/icons-material";
import {
  Box, Drawer, IconButton, InputAdornment, List, ListItemButton, ListItemText,
  Stack, TextField, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { api } from "../../api/client";
import { Markdown } from "./Markdown";

interface Doc { id: string; title: string; markdown: string }
interface Hit { id: string; title: string; section: string; snippet: string }

export function HelpPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const loc = useLocation();
  const navigate = useNavigate();
  const [doc, setDoc] = useState<Doc | null>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadPage = (id: string) => {
    setHits(null); setQ("");
    api.get(`/help/page/${id}`).then(setDoc).catch((e) => setError(e.message));
  };

  // On open, jump to the doc for the current route (context-aware).
  useEffect(() => {
    if (!open) return;
    setError(null);
    api.get(`/help/for-route?route=${encodeURIComponent(loc.pathname)}`)
      .then((r) => loadPage(r?.id || "user-getting-started"))
      .catch((e) => setError(e.message));
  }, [open, loc.pathname]);

  useEffect(() => {
    if (!q.trim()) { setHits(null); return; }
    const t = setTimeout(() => {
      api.get(`/help/search?q=${encodeURIComponent(q)}`).then(setHits).catch(() => setHits([]));
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <Drawer anchor="right" open={open} onClose={onClose}
      PaperProps={{ sx: { width: { xs: "100%", sm: 480 }, maxWidth: "100%" } }}>
      <Stack direction="row" alignItems="center" sx={{ p: 1.5, borderBottom: "1px solid", borderColor: "divider" }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, flex: 1 }}>Help</Typography>
        <IconButton size="small" title="Open full help" onClick={() => { onClose(); navigate("/help"); }}><OpenInFull fontSize="small" /></IconButton>
        <IconButton size="small" onClick={onClose}><Close fontSize="small" /></IconButton>
      </Stack>
      <Box sx={{ p: 1.5, pb: 1 }}>
        <TextField fullWidth size="small" placeholder="Search help…" value={q} onChange={(e) => setQ(e.target.value)}
          InputProps={{ startAdornment: <InputAdornment position="start"><Search fontSize="small" /></InputAdornment> }} />
      </Box>
      <Box sx={{ px: 2, pb: 3, overflowY: "auto" }}>
        {error && <Typography color="error" variant="body2">{error}</Typography>}
        {hits ? (
          hits.length === 0 ? <Typography variant="body2" color="text.secondary">No matches.</Typography> : (
            <List dense>
              {hits.map((h) => (
                <ListItemButton key={h.id} onClick={() => loadPage(h.id)}>
                  <ListItemText primary={h.title} secondary={h.snippet || h.section}
                    primaryTypographyProps={{ fontWeight: 600 }} secondaryTypographyProps={{ noWrap: true }} />
                </ListItemButton>
              ))}
            </List>
          )
        ) : doc ? <Markdown>{doc.markdown}</Markdown> : <Typography variant="body2" color="text.secondary">Loading…</Typography>}
      </Box>
    </Drawer>
  );
}
