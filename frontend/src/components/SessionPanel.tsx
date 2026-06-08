import { Box, Button, Chip, Typography } from "@mui/material";

import { useAuth } from "../auth/AuthContext";

export function SessionPanel() {
  const { principal, logout } = useAuth();
  if (!principal) return null;
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
      <Typography variant="body2">{principal.username}</Typography>
      <Chip size="small" label={principal.role} color="default" />
      <Button color="inherit" size="small" onClick={logout}>
        Logout
      </Button>
    </Box>
  );
}
