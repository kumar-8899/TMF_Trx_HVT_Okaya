import { Add, Search } from "@mui/icons-material";
import {
  Button, InputAdornment, Stack, Table, TableBody, TableCell, TableHead, TableRow,
  TextField,
} from "@mui/material";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageHeader, Section, StatusChip, statusKind } from "../components/ui";
import { MONO_STACK } from "../theme/theme";

interface Summary {
  recipe_id: string;
  name: string;
  status: string;
  latest_version: number;
}

export function Recipes() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [rows, setRows] = useState<Summary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api.get("/recipes").then(setRows).catch((e) => setError(e.message));
  }, []);

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    if (!q) return rows;
    return rows.filter((r) => `${r.name} ${r.recipe_id}`.toLowerCase().includes(q));
  }, [rows, query]);

  return (
    <div>
      <PageHeader
        title="Recipes"
        subtitle="Versioned test recipes"
        actions={can("RECIPE.EDIT") && (
          <Button variant="contained" startIcon={<Add />} onClick={() => navigate("/recipes/new")}>
            New recipe
          </Button>
        )}
      />

      <Section bodyPad={0}>
        <Stack sx={{ p: 2, pb: 1.5 }}>
          <TextField
            placeholder="Search recipes…" value={query} onChange={(e) => setQuery(e.target.value)}
            sx={{ maxWidth: 320 }}
            InputProps={{ startAdornment: <InputAdornment position="start"><Search fontSize="small" /></InputAdornment> }}
          />
        </Stack>
        {filtered.length === 0 ? (
          <EmptyState message={error || (rows.length ? "No recipes match your search." : "No recipes.")} />
        ) : (
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell><TableCell>ID</TableCell>
                <TableCell>Status</TableCell><TableCell>Latest</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filtered.map((r) => (
                <TableRow key={r.recipe_id} hover sx={{ cursor: "pointer" }}
                  onClick={() => navigate(`/recipes/${r.recipe_id}`)}>
                  <TableCell sx={{ fontWeight: 600 }}>{r.name}</TableCell>
                  <TableCell sx={{ fontFamily: MONO_STACK, color: "text.secondary" }}>{r.recipe_id}</TableCell>
                  <TableCell><StatusChip label={r.status} kind={statusKind(r.status)} /></TableCell>
                  <TableCell sx={{ fontFamily: MONO_STACK }}>v{r.latest_version}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>
    </div>
  );
}
