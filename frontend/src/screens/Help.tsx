/** Full help page: sidebar tree + search + markdown. super_admin also sees the
 * Developer docs via the audience toggle (backend gates the dev pages — and a built station
 * never has any). Deep-linkable: `/help?page=<id>#<heading-anchor>`.
 *
 * `embedded` (used by the User Portal's Manual tab): no page header, user audience only, and
 * `help:` links stay inside the portal (`/portal?tab=manual&page=<id>`). */
import Search from "@mui/icons-material/Search";
import {
  Box, InputAdornment, List, ListItemButton, ListItemText, Paper, Stack, TextField,
  ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { HelpLinkBase, Markdown } from "../components/help/Markdown";
import "../components/help/widgets/register";
import { PageHeader, Section } from "../components/ui";

interface PageRef { id: string; title: string; route: string | null; audience: string }
interface SectionT { section: string; audience: string; pages: PageRef[] }
interface Doc { id: string; title: string; markdown: string }
interface Hit { id: string; title: string; section: string; snippet: string }

export function Help({ embedded = false }: { embedded?: boolean }) {
  const [tree, setTree] = useState<SectionT[]>([]);
  const [doc, setDoc] = useState<Doc | null>(null);
  const [aud, setAud] = useState<"user" | "dev">("user");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [params, setParams] = useSearchParams();
  const loc = useLocation();
  const pageParam = params.get("page");
  const load = (id: string) => setParams((prev) => { const n = new URLSearchParams(prev); n.set("page", id); return n; });

  useEffect(() => {
    api.get("/help/index").then(setTree).catch((e) => setError(e.message));
  }, []);

  // The URL (?page=) is the source of truth: sidebar clicks, in-page help: links and shared
  // links all just change it, and this loads the page (switching audience tab if it is a dev page).
  useEffect(() => {
    if (!tree.length) return;
    const id = pageParam ?? tree.find((s) => s.audience === "user")?.pages[0]?.id;
    if (!id) return;
    const owner = tree.find((s) => s.pages.some((p) => p.id === id));
    if (owner) setAud(!embedded && owner.audience === "dev" ? "dev" : "user");
    setHits(null); setQ(""); setError(null);
    api.get(`/help/page/${id}`).then(setDoc).catch((e) => setError(e.message));
  }, [tree, pageParam]);

  useEffect(() => {
    if (doc && loc.hash) {
      const t = setTimeout(() => document.getElementById(loc.hash.slice(1))?.scrollIntoView?.({ block: "start" }), 50);
      return () => clearTimeout(t);
    }
  }, [doc, loc.hash]);

  useEffect(() => {
    if (!q.trim()) { setHits(null); return; }
    const t = setTimeout(() => api.get(`/help/search?q=${encodeURIComponent(q)}`).then(setHits).catch(() => setHits([])), 200);
    return () => clearTimeout(t);
  }, [q]);

  const hasDev = useMemo(() => !embedded && tree.some((s) => s.audience === "dev"), [tree, embedded]);
  const sections = tree.filter((s) => s.audience === aud);

  return (
    <HelpLinkBase.Provider value={embedded ? "/portal?tab=manual" : "/help"}>
    <Box>
      {!embedded && <PageHeader title="Help & Documentation" subtitle="Guides & reference"
        actions={hasDev && (
          <ToggleButtonGroup size="small" exclusive value={aud} onChange={(_, v) => v && setAud(v)}>
            <ToggleButton value="user">User</ToggleButton>
            <ToggleButton value="dev">Developer</ToggleButton>
          </ToggleButtonGroup>
        )} />}
      {error && <Typography color="error" sx={{ mb: 2 }}>{error}</Typography>}

      <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems="stretch">
        <Paper sx={{ width: { xs: "100%", md: 280 }, flexShrink: 0, overflow: "hidden", alignSelf: "flex-start" }}>
          <Box sx={{ p: 1.5 }}>
            <TextField fullWidth size="small" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)}
              InputProps={{ startAdornment: <InputAdornment position="start"><Search fontSize="small" /></InputAdornment> }} />
          </Box>
          <Box sx={{ maxHeight: "70vh", overflowY: "auto", pb: 1 }}>
            {sections.map((s) => (
              <Box key={s.section}>
                <Typography variant="caption" sx={{ display: "block", px: 1.5, pt: 1, color: "text.secondary", textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 700 }}>
                  {s.section}
                </Typography>
                <List dense disablePadding>
                  {s.pages.map((p) => (
                    <ListItemButton key={p.id} selected={doc?.id === p.id} onClick={() => load(p.id)} sx={{ py: 0.25 }}>
                      <ListItemText primary={p.title} primaryTypographyProps={{ fontSize: 13.5 }} />
                    </ListItemButton>
                  ))}
                </List>
              </Box>
            ))}
          </Box>
        </Paper>

        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Section>
            {hits ? (
              hits.length === 0 ? <Typography variant="body2" color="text.secondary">No matches.</Typography> : (
                <List>
                  {hits.map((h) => (
                    <ListItemButton key={h.id} onClick={() => load(h.id)}>
                      <ListItemText primary={h.title} secondary={h.snippet || h.section} primaryTypographyProps={{ fontWeight: 600 }} />
                    </ListItemButton>
                  ))}
                </List>
              )
            ) : doc ? <Markdown>{doc.markdown}</Markdown> : <Typography variant="body2" color="text.secondary">Loading…</Typography>}
          </Section>
        </Box>
      </Stack>
    </Box>
    </HelpLinkBase.Provider>
  );
}
