import {
  Button, Chip, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";

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

  useEffect(() => {
    api.get("/recipes").then(setRows).catch((e) => setError(e.message));
  }, []);

  return (
    <Stack spacing={2}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="h5">Recipes</Typography>
        {can("RECIPE.EDIT") && (
          <Button variant="contained" onClick={() => navigate("/recipes/new")}>New recipe</Button>
        )}
      </Stack>
      {error && <Typography color="error">{error}</Typography>}
      <Paper>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell><TableCell>ID</TableCell>
              <TableCell>Status</TableCell><TableCell>Latest</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.recipe_id} hover sx={{ cursor: "pointer" }}
                onClick={() => navigate(`/recipes/${r.recipe_id}`)}>
                <TableCell>{r.name}</TableCell>
                <TableCell>{r.recipe_id}</TableCell>
                <TableCell><Chip size="small" label={r.status}
                  color={r.status === "active" ? "success" : "default"} /></TableCell>
                <TableCell>v{r.latest_version}</TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && <TableRow><TableCell colSpan={4}>No recipes.</TableCell></TableRow>}
          </TableBody>
        </Table>
      </Paper>
    </Stack>
  );
}
