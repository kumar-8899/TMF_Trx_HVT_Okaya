import { Add, ContentCopy, Download, Edit, FileUpload, Search, Visibility } from "@mui/icons-material";
import {
  Box, Button, Chip, IconButton, InputAdornment, MenuItem, Paper, Stack, Table,
  TableBody, TableCell, TableHead, TableRow, TableSortLabel, TextField, Tooltip, Typography,
} from "@mui/material";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageHeader, Section, StatusChip, StatusDot, statusKind } from "../components/ui";
import { MONO_STACK } from "../theme/theme";

interface Summary {
  recipe_id: string;
  name: string;
  status: string;
  latest_version: number;
  tags?: string[];
}

type SortKey = "name" | "status" | "latest_version";

function CountCard({ label, value, kind }: { label: string; value: number; kind?: "pass" | "running" }) {
  return (
    <Paper sx={{ p: 2, flex: 1, minWidth: 120 }}>
      <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {label}
      </Typography>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mt: 0.5 }}>
        {kind && <StatusDot kind={kind} />}
        <Typography variant="h4">{value}</Typography>
      </Stack>
    </Paper>
  );
}

export function Recipes() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [rows, setRows] = useState<Summary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () => api.get("/recipes").then(setRows).catch((e) => setError(e.message));
  useEffect(() => { refresh(); }, []);

  const counts = useMemo(() => ({
    total: rows.length,
    active: rows.filter((r) => r.status === "active").length,
    draft: rows.filter((r) => r.status === "draft").length,
  }), [rows]);

  const view = useMemo(() => {
    const q = query.toLowerCase().trim();
    let out = rows.filter((r) =>
      (!statusFilter || r.status === statusFilter) &&
      (!q || `${r.name} ${r.recipe_id} ${(r.tags || []).join(" ")}`.toLowerCase().includes(q)));
    out = [...out].sort((a, b) => {
      const av = a[sortKey] ?? "", bv = b[sortKey] ?? "";
      const cmp = typeof av === "number" && typeof bv === "number"
        ? av - bv : String(av).localeCompare(String(bv));
      return sortDir === "asc" ? cmp : -cmp;
    });
    return out;
  }, [rows, query, statusFilter, sortKey, sortDir]);

  const sort = (key: SortKey) => {
    if (key === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("asc"); }
  };

  const edit = async (id: string) => {
    // fork a draft of the latest version → editing publishes as a NEW version (same id)
    setError(null);
    try {
      const res = await api.post(`/recipes/${id}/drafts`);
      navigate(`/recipes/${id}/edit`, { state: { recipeId: id, draftId: res.draft_id, recipe: res.recipe } });
    } catch (e: any) { setError(e.message); }
  };

  const duplicate = async (id: string) => {
    setError(null);
    try {
      const recipe = await api.get(`/recipes/${id}`);   // latest published version
      navigate("/recipes/new", { state: { recipe: { ...recipe, recipe_id: id }, duplicate: true } });
    } catch (e: any) { setError(e.message); }
  };

  const exportRecipe = async (id: string) => {
    const tok = localStorage.getItem("tmf.token");
    const res = await fetch(`/recipes/${id}/export?versions=latest`, { headers: tok ? { Authorization: `Bearer ${tok}` } : {} });
    if (!res.ok) { setError(`export failed (${res.status})`); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `recipe-${id}.zip`; a.click();
    URL.revokeObjectURL(url);
  };

  const onImportFile = async (file: File) => {
    setError(null); setNotice(null);
    try {
      // The export is a ZIP bundle — upload the raw bytes (NOT JSON).
      const tok = localStorage.getItem("tmf.token");
      const r = await fetch(`/recipes/import?mode=add`, {
        method: "POST",
        headers: { "Content-Type": "application/zip", ...(tok ? { Authorization: `Bearer ${tok}` } : {}) },
        body: file,
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || `import failed (${r.status})`);
      const n = Array.isArray(data.imported) ? data.imported.length : (data.imported ?? 0);
      const skipped = Array.isArray(data.skipped) ? data.skipped.length : 0;
      setNotice(`Imported ${n} recipe(s)${skipped ? `, ${skipped} skipped (already exist)` : ""}.`);
      refresh();
    } catch (e: any) { setError(e?.message || "Import failed"); }
  };

  return (
    <Box>
      <PageHeader
        title="Recipes"
        subtitle="Versioned test recipes"
        actions={
          <>
            {can("RECIPE.EDIT") && (
              <Button variant="outlined" color="inherit" startIcon={<FileUpload />} onClick={() => fileRef.current?.click()}>
                Import
              </Button>
            )}
            {can("RECIPE.EDIT") && (
              <Button variant="contained" startIcon={<Add />} onClick={() => navigate("/recipes/new")}>
                New recipe
              </Button>
            )}
            <input ref={fileRef} type="file" accept="application/zip,.zip" hidden
              onChange={(e) => { const f = e.target.files?.[0]; if (f) onImportFile(f); e.target.value = ""; }} />
          </>
        }
      />
      {error && <Typography color="error" sx={{ mb: 2 }}>{error}</Typography>}
      {notice && <Typography color="success.main" sx={{ mb: 2 }}>{notice}</Typography>}

      <Stack direction="row" spacing={2} sx={{ mb: 2 }} flexWrap="wrap" useFlexGap>
        <CountCard label="recipes" value={counts.total} />
        <CountCard label="active" value={counts.active} kind="pass" />
        <CountCard label="drafts" value={counts.draft} kind="running" />
      </Stack>

      <Section bodyPad={0}>
        <Stack direction="row" spacing={1.5} sx={{ p: 2, pb: 1.5 }} flexWrap="wrap" useFlexGap alignItems="center">
          <TextField placeholder="Search recipes…" value={query} onChange={(e) => setQuery(e.target.value)}
            sx={{ maxWidth: 320, flex: 1 }}
            InputProps={{ startAdornment: <InputAdornment position="start"><Search fontSize="small" /></InputAdornment> }} />
          <TextField select label="Status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} sx={{ width: 140 }}>
            <MenuItem value="">All</MenuItem>
            <MenuItem value="active">Active</MenuItem>
            <MenuItem value="draft">Draft</MenuItem>
          </TextField>
        </Stack>

        {view.length === 0 ? (
          <EmptyState message={error || (rows.length ? "No recipes match your filters." : "No recipes.")} />
        ) : (
          <Table>
            <TableHead>
              <TableRow>
                <TableCell sortDirection={sortKey === "name" ? sortDir : false}>
                  <TableSortLabel active={sortKey === "name"} direction={sortKey === "name" ? sortDir : "asc"} onClick={() => sort("name")}>Name</TableSortLabel>
                </TableCell>
                <TableCell>ID</TableCell>
                <TableCell sortDirection={sortKey === "status" ? sortDir : false}>
                  <TableSortLabel active={sortKey === "status"} direction={sortKey === "status" ? sortDir : "asc"} onClick={() => sort("status")}>Status</TableSortLabel>
                </TableCell>
                <TableCell sortDirection={sortKey === "latest_version" ? sortDir : false}>
                  <TableSortLabel active={sortKey === "latest_version"} direction={sortKey === "latest_version" ? sortDir : "asc"} onClick={() => sort("latest_version")}>Latest</TableSortLabel>
                </TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {view.map((r) => (
                <TableRow key={r.recipe_id} hover sx={{ cursor: "pointer" }} onClick={() => navigate(`/recipes/${r.recipe_id}`)}>
                  <TableCell sx={{ fontWeight: 600 }}>{r.name}</TableCell>
                  <TableCell sx={{ fontFamily: MONO_STACK, color: "text.secondary" }}>{r.recipe_id}</TableCell>
                  <TableCell><StatusChip label={r.status} kind={statusKind(r.status)} /></TableCell>
                  <TableCell><Chip size="small" variant="outlined" label={`v${r.latest_version}`} sx={{ fontFamily: MONO_STACK }} /></TableCell>
                  <TableCell align="right" onClick={(e) => e.stopPropagation()}>
                    <Tooltip title="View"><IconButton size="small" onClick={() => navigate(`/recipes/${r.recipe_id}`)}><Visibility fontSize="small" /></IconButton></Tooltip>
                    {can("RECIPE.EDIT") && <Tooltip title="Edit (new version)"><IconButton size="small" onClick={() => edit(r.recipe_id)}><Edit fontSize="small" /></IconButton></Tooltip>}
                    {can("RECIPE.EDIT") && <Tooltip title="Duplicate (new editable id)"><IconButton size="small" onClick={() => duplicate(r.recipe_id)}><ContentCopy fontSize="small" /></IconButton></Tooltip>}
                    <Tooltip title="Export"><IconButton size="small" onClick={() => exportRecipe(r.recipe_id)}><Download fontSize="small" /></IconButton></Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>
    </Box>
  );
}
