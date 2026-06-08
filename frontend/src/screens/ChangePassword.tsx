import { Alert, Box, Button, Card, CardContent, Stack, TextField, Typography } from "@mui/material";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

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
    <Box sx={{ display: "flex", justifyContent: "center", mt: 10 }}>
      <Card sx={{ width: 360 }}>
        <CardContent>
          <Typography variant="h5" gutterBottom>Change password</Typography>
          {mustChangePassword && (
            <Alert severity="info" sx={{ mb: 2 }}>A password change is required before continuing.</Alert>
          )}
          <form onSubmit={submit}>
            <Stack spacing={2}>
              <TextField label="Current password" type="password" value={oldPw}
                onChange={(e) => setOld(e.target.value)} inputProps={{ "aria-label": "old" }} />
              <TextField label="New password" type="password" value={newPw}
                onChange={(e) => setNew(e.target.value)} inputProps={{ "aria-label": "new" }} />
              {error && <Alert severity="error">{error}</Alert>}
              <Button type="submit" variant="contained" disabled={busy}>Update</Button>
            </Stack>
          </form>
        </CardContent>
      </Card>
    </Box>
  );
}
