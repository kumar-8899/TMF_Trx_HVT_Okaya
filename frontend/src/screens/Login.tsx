import { Alert, Box, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { BrandMark } from "../components/BrandMark";

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const p = await login(username, password);
      navigate(p.must_change_password ? "/change-password" : "/");
    } catch (err: any) {
      setError(err?.message || "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box
      sx={{
        minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
        p: 2, bgcolor: "background.default",
        backgroundImage: (t) =>
          `radial-gradient(1200px 600px at 50% -10%, ${t.palette.primary.dark}22, transparent)`,
      }}
    >
      <Paper sx={{ width: 380, p: 4 }}>
        <Stack spacing={3}>
          <Stack spacing={1} alignItems="center">
            <BrandMark size={44} />
            <Typography variant="h5">Test &amp; Measurement</Typography>
            <Typography variant="body2" color="text.secondary">Sign in to the station</Typography>
          </Stack>
          <form onSubmit={submit}>
            <Stack spacing={2}>
              <TextField label="Username" value={username} autoFocus fullWidth
                onChange={(e) => setUsername(e.target.value)} inputProps={{ "aria-label": "username" }} />
              <TextField label="Password" type="password" value={password} fullWidth
                onChange={(e) => setPassword(e.target.value)} inputProps={{ "aria-label": "password" }} />
              {error && <Alert severity="error">{error}</Alert>}
              <Button type="submit" variant="contained" size="large" disabled={busy} fullWidth>
                Log in
              </Button>
              <Typography variant="caption" color="text.secondary" align="center">
                Forgot your password? Ask an administrator to reset it.
              </Typography>
            </Stack>
          </form>
        </Stack>
      </Paper>
    </Box>
  );
}
