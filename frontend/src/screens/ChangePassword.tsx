import { Alert, Box, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { BrandMark } from "../components/BrandMark";

export function ChangePassword() {
  const { changePassword, mustChangePassword } = useAuth();
  const navigate = useNavigate();
  const [oldPw, setOld] = useState("");
  const [newPw, setNew] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await changePassword(oldPw, newPw);
      navigate("/");
    } catch (err: any) {
      setError(err?.message || "Change failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box
      sx={{
        minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
        p: 2, bgcolor: "background.default",
      }}
    >
      <Paper sx={{ width: 380, p: 4 }}>
        <Stack spacing={3}>
          <Stack spacing={1} alignItems="center">
            <BrandMark size={44} />
            <Typography variant="h5">Change password</Typography>
          </Stack>
          {mustChangePassword && (
            <Alert severity="info">A password change is required before continuing.</Alert>
          )}
          <form onSubmit={submit}>
            <Stack spacing={2}>
              <TextField label="Current password" type="password" value={oldPw} fullWidth
                onChange={(e) => setOld(e.target.value)} inputProps={{ "aria-label": "old" }} />
              <TextField label="New password" type="password" value={newPw} fullWidth
                onChange={(e) => setNew(e.target.value)} inputProps={{ "aria-label": "new" }} />
              {error && <Alert severity="error">{error}</Alert>}
              <Button type="submit" variant="contained" size="large" disabled={busy} fullWidth>
                Update
              </Button>
            </Stack>
          </form>
        </Stack>
      </Paper>
    </Box>
  );
}
