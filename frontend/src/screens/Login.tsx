import { Alert, Box, Button, Card, CardContent, Stack, TextField, Typography } from "@mui/material";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

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
    <Box sx={{ display: "flex", justifyContent: "center", mt: 10 }}>
      <Card sx={{ width: 360 }}>
        <CardContent>
          <Typography variant="h5" gutterBottom>Sign in</Typography>
          <form onSubmit={submit}>
            <Stack spacing={2}>
              <TextField label="Username" value={username} autoFocus
                onChange={(e) => setUsername(e.target.value)} inputProps={{ "aria-label": "username" }} />
              <TextField label="Password" type="password" value={password}
                onChange={(e) => setPassword(e.target.value)} inputProps={{ "aria-label": "password" }} />
              {error && <Alert severity="error">{error}</Alert>}
              <Button type="submit" variant="contained" disabled={busy}>Log in</Button>
              <Typography variant="caption" color="text.secondary">
                Forgot your password? Ask an administrator to reset it.
              </Typography>
            </Stack>
          </form>
        </CardContent>
      </Card>
    </Box>
  );
}
