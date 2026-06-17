import { Close, Login as LoginIcon, ShieldOutlined } from "@mui/icons-material";
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

  const now = new Date();
  const stamp =
    now.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) +
    " — " + now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

  return (
    <Box sx={{
      minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
      p: 2, bgcolor: "background.default",
    }}>
      <Paper sx={{ width: 720, maxWidth: "100%", overflow: "hidden" }}>
        <Box sx={{ display: "flex", flexDirection: { xs: "column", sm: "row" } }}>
          {/* Left navy identity panel */}
          <Box sx={{
            width: { xs: "100%", sm: 270 }, flexShrink: 0,
            bgcolor: "sectionHeader", color: "onNavy",
            p: 4, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 1.5,
          }}>
            <BrandMark size={56} />
            <Typography variant="h6" sx={{ color: "onNavy", textAlign: "center" }}>Test &amp; Measurement</Typography>
            <Typography variant="caption" sx={{ color: "rgba(255,255,255,0.6)", textAlign: "center", lineHeight: 1.6 }}>
              Authorised access only.<br />All sessions are encrypted.
            </Typography>
          </Box>

          {/* Right form panel */}
          <Box sx={{ flex: 1, p: { xs: 3, sm: 4 } }}>
            <Typography variant="h6">Sign in to continue</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>Enter your credentials below</Typography>

            <form onSubmit={submit}>
              <Stack spacing={2}>
                <TextField label="Username" value={username} autoFocus fullWidth
                  onChange={(e) => setUsername(e.target.value)} inputProps={{ "aria-label": "username" }} />
                <TextField label="Password" type="password" value={password} fullWidth
                  onChange={(e) => setPassword(e.target.value)} inputProps={{ "aria-label": "password" }} />
                {error && <Alert severity="error">{error}</Alert>}
                <Stack direction="row" spacing={1.5}>
                  <Button type="submit" variant="contained" size="large" startIcon={<LoginIcon />} disabled={busy} sx={{ flex: 1 }}>
                    Log in
                  </Button>
                  <Button type="button" variant="outlined" color="inherit" size="large" startIcon={<Close />}
                    onClick={() => { setUsername(""); setPassword(""); setError(null); }} sx={{ flex: 1 }}>
                    Cancel
                  </Button>
                </Stack>
              </Stack>
            </form>

            <Box sx={{
              mt: 2.5, p: 1.5, borderRadius: 2, display: "flex", alignItems: "center", gap: 1,
              bgcolor: (t) => (t.palette.mode === "dark" ? "rgba(46,139,79,0.12)" : "#F0F7F3"),
              border: (t) => `1px solid ${t.palette.mode === "dark" ? "rgba(46,139,79,0.3)" : "#C3DFD0"}`,
            }}>
              <ShieldOutlined sx={{ color: "primary.main", fontSize: 20 }} />
              <Typography variant="caption" color="text.secondary">
                Connection is secure. Credentials are encrypted during transmission.
              </Typography>
            </Box>
          </Box>
        </Box>

        <Box sx={{
          px: 2.5, py: 1, borderTop: "1px solid", borderColor: "divider",
          display: "flex", justifyContent: "space-between",
          bgcolor: (t) => (t.palette.mode === "dark" ? "rgba(255,255,255,0.02)" : "#F9FAFB"),
        }}>
          <Typography variant="caption" color="text.secondary">{stamp}</Typography>
          <Typography variant="caption" color="text.secondary">v1.0.0</Typography>
        </Box>
      </Paper>
    </Box>
  );
}
